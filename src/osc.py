from pythonosc import udp_client, dispatcher, osc_server
from tinyoscquery.queryservice import OSCQueryService
from tinyoscquery.utility import get_open_tcp_port, get_open_udp_port, check_if_tcp_port_open, check_if_udp_port_open
from tinyoscquery.query import OSCQueryBrowser, OSCQueryClient
import time
import os
from threading import Thread
from psutil import process_iter

AVATAR_PARAMETERS_PREFIX = "/avatar/parameters/"
AVATAR_CHANGE_PARAMETER = "/avatar/change"

class OSC:
    def __init__(self, conf: dict, avatar_change_function) -> None:
        self.ip = conf["IP"]
        self.port = conf["Port"]
        self.server_port = conf["Server_Port"]
        self.http_port = conf["HTTP_Port"]
        self.stick_tolerance = int(conf['StickMoveTolerance']) / 100
        self.curr_avatar = ""
        self.curr_time = 0

        self.osc_client = udp_client.SimpleUDPClient(self.ip, self.port)
        self.disp = dispatcher.Dispatcher()
        self.disp.map(AVATAR_CHANGE_PARAMETER, avatar_change_function)
        if self.server_port != 9001:
            print("OSC Server port is not default, testing port availability and advertising OSCQuery endpoints")
            if self.server_port <= 0 or not check_if_udp_port_open(self.server_port):
                self.server_port = get_open_udp_port()
            if self.http_port <= 0 or not check_if_tcp_port_open(self.http_port):
                self.http_port = self.server_port if check_if_tcp_port_open(self.server_port) else get_open_tcp_port()
        else:
            print("OSC Server port is default.")

        print("Waiting for VRChat to start.")
        while not self.is_running():
            time.sleep(3)
        print("VRChat started!")
        self.qclient = self._wait_get_oscquery_client()
        self.curr_avatar = self.qclient.query_node(AVATAR_CHANGE_PARAMETER).value[0]
        self.server = osc_server.ThreadingOSCUDPServer((self.ip, self.server_port), self.disp)
        server_thread = Thread(target=self._osc_server_serve, daemon=True)
        server_thread.start()
        self.oscqs = OSCQueryService("ThumbParamsOSC", self.http_port, self.server_port)
        self.oscqs.advertise_endpoint(AVATAR_CHANGE_PARAMETER, access="readwrite")


    def is_running(self) -> bool:
        """
        Checks if VRChat is running.
        Returns:
            bool: True if VRChat is running, False if not
        """
        _proc_name = "VRChat.exe" if os.name == 'nt' else "VRChat"
        return _proc_name in (p.name() for p in process_iter())


    def _wait_get_oscquery_client(self) -> OSCQueryClient:
        """
        Waits for VRChat to be discovered and ready and returns the OSCQueryClient.
        Returns:
            OSCQueryClient: OSCQueryClient for VRChat
        """
        service_info = None
        print("Waiting for VRChat to be discovered.")
        while service_info is None:
            browser = OSCQueryBrowser()
            time.sleep(2) # Wait for discovery
            service_info = browser.find_service_by_name("VRChat")
        print("VRChat discovered!")
        client = OSCQueryClient(service_info)
        print("Waiting for VRChat to be ready.")
        while client.query_node(AVATAR_CHANGE_PARAMETER) is None:
            time.sleep(2)
        print("VRChat ready!")
        return client


    def _osc_server_serve(self) -> None:
        """
        Starts the OSC server.
        Returns:
            None
        """
        print(f"Starting OSC client on {self.ip}:{self.server_port}:{self.http_port}")
        self.server.serve_forever(2)


    def _send_parameter(self, parameter: str, value) -> None:
        """
        Sends a parameter to VRChat via OSC.
        Parameters:
            parameter (str): Name of the parameter
            value (any): Value of the parameter
            floating (str): Floating value of the parameter, just for for debug output
        Returns:
            None
        """
        self.osc_client.send_message(AVATAR_PARAMETERS_PREFIX + parameter, value)


    def _send_boolean_toggle(self, action: dict, value: bool) -> None:
        """
        Sends a boolean action as a toggle to VRChat via OSC.
        Parameters:
            action (dict): Action
            value (bool): Value of the parameter
        Returns:
            None
        """
        if not action["enabled"]:
            return
        
        if value:
            action["last_value"] = not action["last_value"]
            time.sleep(0.1)
            self._send_parameter(action["osc_parameter"], action["last_value"])
            return
        
        if action["always"]:
            self._send_parameter(action["osc_parameter"], action["last_value"])


    def _send_boolean(self, action: dict, value: bool) -> None:
        """
        Sends a boolean action to VRChat via OSC.
        Parameters:
            action (dict): Action
            value (bool): Value of the parameter
        Returns:
            None
        """

        if not action["enabled"] or (not action["always"] and action["last_value"] == value):
            return

        if action["floating"]:
            if value:
                action["timestamp"] = self.curr_time
            elif not value and self.curr_time - action["timestamp"] <= action["floating"]: 
                value = action["last_value"]
        
        if not action["always"]:
            action["last_value"] = value
        else:
            self._send_parameter(action["osc_parameter"], value)


    def _send_vector1(self, action: dict, value: float) -> None:
        """
        Sends a vector1 action to VRChat via OSC.
        Parameters:
            action (dict): Action
            value (float): Value of the parameter
        Returns:
            None
        """

        if not action["enabled"] or (not action["always"] and action["last_value"] == value):
            return
        
        if action["floating"]:
            if value > action["last_value"]:
                action["timestamp"] = self.curr_time
            elif value < action["last_value"] and self.curr_time - action["timestamp"] <= action["floating"]: 
                value = action["last_value"]

        if not action["always"]:
            action["last_value"] = value
        else:
            self._send_parameter(action["osc_parameter"], value)


    def _send_vector2(self, action: dict, value: tuple) -> None:
        """
        Sends a vector2 action to VRChat via OSC.
        Parameters:
            action (dict): Action
            value (tuple): X and Y value of the parameter in a tuple
        Returns:
            None
        """
        val_x, val_y = value
        tmp = (val_x > self.stick_tolerance or val_y > self.stick_tolerance) or (val_x < -self.stick_tolerance or val_y < -self.stick_tolerance)

        if action["floating"]:
            if val_x:
                action["timestamp"][0] = self.curr_time
            elif not val_x and self.curr_time - action["timestamp"][0] <= action["floating"][0]: 
                val_x = action["last_value"][0]
            if val_y:
                action["timestamp"][1] = self.curr_time
            elif not val_y and self.curr_time - action["timestamp"][1] <= action["floating"][1]:
                val_y = action["last_value"][1]

        if not action["always"]:
            action["last_value"] = [val_x, val_y, tmp]

        if action["enabled"][0] and (action["always"][0] or action["last_value"][0] != val_x):
            self._send_parameter(action["osc_parameter"][0], val_x)
        if action["enabled"][1] and (action["always"][1] or action["last_value"][1] != val_y):
            self._send_parameter(action["osc_parameter"][1], val_y)
        if len(action["osc_parameter"]) > 2 and action["enabled"][2] and (action["always"][2] or action["last_value"][2] != tmp):
            self._send_parameter(action["osc_parameter"][2], tmp)


    def refresh_time(self) -> None:
        """
        Refreshes the current time.
        Returns:
            None
        """
        self.curr_time = time.time()


    def send(self, action: dict | str, value: bool | float | tuple) -> None:
        """
        Sends an OSC message to VRChat.
        Parameters:
            action (dict | str): Action or OSC address
            value (bool | float | tuple): Value of the parameter
        Returns:
            None
        """
        if isinstance(action, str):
            self._send_parameter(action, value)
            return
        
        match action['type']:
            case "boolean":
                if action["floating"] == -1:
                    self._send_boolean_toggle(action, value)
                else:
                    self._send_boolean(action, value)
            case "vector1":
                self._send_vector1(action, value)
            case "vector2":
                self._send_vector2(action, value)
            case _:
                raise TypeError("Unknown action type: " + action['type'])
