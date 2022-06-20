"""
GROWATT SOLAR POWER MONITOR FOR ADAFRUIT MATRIX PORTAL
"""
import gc
import time
import json
import board
import busio
from digitalio import DigitalInOut
import adafruit_esp32spi.adafruit_esp32spi_socket as socket
from adafruit_esp32spi import adafruit_esp32spi
import adafruit_requests as requests
from adafruit_hashlib import md5
from adafruit_matrixportal.matrix import Matrix
from adafruit_display_text.label import Label
import displayio
import terminalio
import neopixel


# RETRY WITH ALL EXCEPTIONS?
# You have the option to catch all exceptions and retry. This can help when adafruit_requests occasionally runs into
# trouble for no discernable reason. There is probably a better way of doing this, but it's what I came up with!
always_retry_after_any_exception = False
if always_retry_after_any_exception:
    print("The script is set to retry after any exception. This may cause odd behaviour from the board.")


# GRAPHICS
matrix = Matrix()
display = matrix.display
group = displayio.Group()
font = terminalio.FONT
display.show(group)
# Colour definitions. These are somewhat dimmed since Neopixels are power hungry, and we want to save electricity, as
# well as work well with a small power supply.
color = displayio.Palette(5)
color[0] = 0x000000  # Black
color[1] = 0x880000  # Soft red
color[2] = 0x888800  # Soft yellow
color[3] = 0x008800  # Soft green
color[4] = 0x000088  # Soft blue


# SOLAR POWER DISPLAY
class SolarPowerDisplay:
    def __init__(self):
        # Minimum power threshold: the wattage at which it becomes useful to turn on the display. Some systems produce
        # a small amount of power even after the sun has set, but you might not want to show that.
        self.minimum_power_threshold: int = 10
        self.title = Label(font, text="Growatt", color=color[3])
        self.title.anchor_point = (0, 0)
        self.title.anchored_position = (0, 0)
        group.insert(0, self.title)
        self.readout = Label(font, text="Loading...", color=color[2])
        self.readout.anchor_point = (0.5, 1)
        self.readout.anchored_position = (display.width // 2, display.height - 2)
        group.insert(1, self.readout)

    def show_readout_placeholder(self):
        self.readout.text = ". . ."

    def update_display(self, power):
        # This function is designed to send Wattage to the display. It accepts integers only. Any 0 in the power reading
        # is replaced with O to make it easier for kids to read.
        if power is None:
            return
        gc.collect()
        if power < self.minimum_power_threshold:
            self.title.color = color[0]
            self.readout.color = color[0]
        else:
            # Change the colour of the readout based on power level. The default settings aim to show when you can start
            # to run large appliances, assuming a typical large appliance uses 1,000-2,000 Watts.
            self.title.text = "Solar power"
            self.title.color = color[3]
            if power < 1500:
                self.readout.color = color[1]
            elif power < 2500:
                self.readout.color = color[2]
            else:
                self.readout.color = color[3]
        self.readout.text = str(power).replace("0", "O") + " W"


#  STATUS NEOPIXEL
#  Green = loading; yellow = preparing API call or processing API response; blue = making API call;
#  red = exception handling.
status_neopixel = neopixel.NeoPixel(
    board.NEOPIXEL, 1, brightness=0.05, auto_write=True, pixel_order=neopixel.GRB
)
status_neopixel.fill(color[3])


# SECRETS
# Access secrets.py to get the Wi-Fi and Growatt account details, including an optional growatt_plant_id if you have
# more than one plant.
try:
    from secrets import secrets
except ImportError:
    print("Could not find secrets.py")
    raise
ssid = secrets["ssid"]
wifi_password = secrets["password"]
username = secrets["growatt_username"]
password = secrets["growatt_password"]
try:
    plant_id = secrets["growatt_plant_id"]
except KeyError:
    print("secrets.py did not specify a Growatt plant ID")
    plant_id = None
del secrets


"""
WI-FI CONTROLLER
This class controls the ESP32 Wi-Fi on the Adafruit Matrix Portal M4. Normally this would be done with the Adafruit 
Matrix Portal class, but that hasn't been implemented due to: a) we need to use HTTP POST to log in, but that is a 
protected method within the Matrix Portal network code and b) the Matrix Portal's fetch function doesn't support the 
cookie handling code used in the API class below. (Please put me out of my misery if there is a better way to do all of
that!)
"""


class WiFiControl:
    def __init__(self, ssid=None, wifi_password=None, connect=False):
        self.ssid = ssid
        self.wifi_password = wifi_password
        self.esp32_cs = DigitalInOut(board.ESP_CS)
        self.esp32_ready = DigitalInOut(board.ESP_BUSY)
        self.esp32_reset = DigitalInOut(board.ESP_RESET)
        self.spi = None
        self.esp = None
        self.spi_setup()
        if connect:
            self.connect()

    def spi_setup(self):
        gc.collect()
        self.spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
        self.esp = adafruit_esp32spi.ESP_SPIcontrol(
            self.spi,
            self.esp32_cs,
            self.esp32_ready,
            self.esp32_reset)

    def connect(self):
        print("Connecting to AP...")
        while not self.esp.is_connected:
            try:
                self.esp.connect_AP(self.ssid, self.wifi_password)
            except RuntimeError as error:
                print("Could not connect to AP, retrying: ", error)
                continue
        print("Connected to", str(self.esp.ssid, "utf-8"), "\tRSSI:", self.esp.rssi)
        socket.set_interface(self.esp)
        requests.set_socket(socket, self.esp)

    def reset(self):
        # Technically a "hard reset" according to the docs.
        print("Initiated Wi-Fi reset.")
        self.esp.reset()
        self.connect()


"""
GROWATT API INTERFACE
The GrowattApi class and hash_password function were adapted from PyPi_GrowattServer:
https://github.com/indykoning/PyPi_GrowattServer. All issues, mistakes, bugs, idiocy are mine. 

This class handles cookies and other headers manually and does not use requests.session() because of the difficulty of 
getting an SSL context running on the Matrix Portal. Ideas to fix this are welcome, e.g. how to get the fake SSL context
working. Ideas on how to avoid/handle exceptions in the API calls are also welcome. 

The API can provide a lot of interesting data - try looking at the API responses if you want to see all the options.
"""


def hash_password(password):
    password_md5 = md5(password.encode('utf-8')).hexdigest()
    for i in range(0, len(password_md5), 2):
        if password_md5[i] == '0':
            password_md5 = password_md5[0:i] + 'c' + password_md5[i + 1:]
    return password_md5


class WiFiNotConnected(Exception):
    # Wi-Fi is not connected.
    pass


class NotLoggedIn(Exception):
    # The API response indicates there is not a valid session.
    pass


class SerialLoginErrors(Exception):
    # Wi-Fi appears to be connected but we can't log in despite several tries.
    pass


class GrowattApi:
    server_url = 'https://server-api.growatt.com/'
    plant_id: str = None
    cookies: str = None
    power: int = None  # The API is set up to give current power only.
    #  If we're handling cookies, adafruit_requests seemingly requires us to set the whole header manually. The
    #  following headers work:
    headers = {
        "User-Agent": "Adafruit CircuitPython",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    def get_url(self, page):
        return self.server_url + page

    def login(self, username, password, plant_id=None):
        password = hash_password(password)
        if plant_id is not None:
            self.plant_id = plant_id
            print("A plant_id has been specified up front:", self.plant_id)
        for i in range(1, 3):
            try:
                status_neopixel.fill(color[2])
                print("Trying login, attempt ", i)
                gc.collect()
                if not wifi.esp.is_connected:
                    raise WiFiNotConnected("Wifi not connected")
                response = requests.post(self.get_url('newTwoLoginAPI.do'), headers=self.headers, data={
                    'userName': username,
                    'password': password
                }, stream=True)
                data = json.loads(response.content.decode('utf-8'))['back']
                if data['success']:
                    data.update({
                        'userId': data['user']['id'],
                        'userLevel': data['user']['rightlevel']
                    })
                else:
                    print("Received response: login unsuccessful")
                    response.close()
                    del response
                    raise NotLoggedIn
                # Default to getting data on the plant most recently added to the account:
                if self.plant_id is None:
                    self.plant_id = data['data'][0]['plantId']
                    print("No plant_id specified up front. Defaulting to", self.plant_id)
                self.cookies = response.headers['set-cookie']
                response.close()
                del response
                return
            # Errors where it's worth trying to log in again:
            except(RuntimeError, ValueError, requests.OutOfRetries, WiFiNotConnected) as error:
                print("Request failed:", error)
                gc.collect()
                status_neopixel.fill(color[1])
                if i >= 2:
                    raise SerialLoginErrors("Serial login errors. Let's try something else!")
                if str(error) != "WiFi not connected":
                    if str(error) != "Error response to command":
                        time.sleep(20)
                    else:
                        wifi.reset()
                else:
                    wifi.connect()

    def get_plant_info(self):
        for i in range(1, 4):
            try:
                status_neopixel.fill(color[2])
                print("Trying to get plant info, attempt ", i)
                gc.collect()
                if not wifi.esp.is_connected:
                    raise WiFiNotConnected("Wifi not connected")
                self.headers['Cookie'] = self.cookies
                url = "{0}?op=getAllDeviceList&plantId={1}&pageNum=1&pageSize=1".format(
                    self.get_url('newTwoPlantAPI.do'), str(self.plant_id))
                status_neopixel.fill(color[4])
                response = requests.get(url, headers=self.headers, stream=True)
                status_neopixel.fill(color[2])
                if response.status_code != 200:
                    print("Response didn't have plant info. HTTP status code: ", response.status_code)
                    response.close()
                    del response
                    raise NotLoggedIn("Apparently not logged in")
                data = json.loads(response.content.decode('utf-8'))
                current_reading = data['deviceList'][0]['power']
                response.close()
                del response, data
                # Store the power reading. The float () and int() methods are used so that we can sanitise the API
                # response, round current_reading to the nearest integer, and make sure any garbage data will throw an
                # exception that can be handled appropriately below.
                self.power = int(float(current_reading))
                return
            # Errors where it's worth retrying:
            except(RuntimeError, ValueError, requests.OutOfRetries, WiFiNotConnected) as error:
                print("Request failed:", error)
                gc.collect()
                status_neopixel.fill(color[1])
                if i >= 3:
                    print("Giving up requesting")
                    raise NotLoggedIn("Serial errors. Trying login again.")
                if str(error) != "WiFi not connected":
                    if str(error) != "Error response to command":
                        time.sleep(20)
                    else:
                        wifi.reset()
                else:
                    wifi.connect()


# Let's go!
display = SolarPowerDisplay()
wifi = WiFiControl(ssid, wifi_password, connect=True)
api = GrowattApi()
display.readout.text = "Logging in"
while True:
    try:
        api.login(username, password, plant_id)
        while True:
            try:
                display.show_readout_placeholder()  # Makes it more obvious if the board freezes on an API call.
                api.get_plant_info()
                display.update_display(api.power)
                status_neopixel.fill(color[0])
                gc.collect()
                if api.power is not None:
                    if display.minimum_power_threshold <= api.power:
                        time.sleep(60 * 2)  # The API  updated every four minutes last time I checked.
                    else:
                        time.sleep(60 * 20)
            # HANDLE EXCEPTIONS
            # Handling exceptions properly is essential for this code to run for a long time. There could be room for
            # improvement in the code below, but it has gone well in testing.
            except NotLoggedIn:
                status_neopixel.fill(color[1])
                print("Seems like we might not be logged in. Logging in again.")
                gc.collect()
                break
    except NotLoggedIn:
        status_neopixel.fill(color[1])
        print("Received response: login unsuccessful. Your account details might be wrong.")
        exit(1)
    except SerialLoginErrors:
        status_neopixel.fill(color[1])
        print("Caught error for multiple failed logins. Let's try resetting the Wi-Fi.")
        gc.collect()
        wifi.reset()
        pass
    except:
        print("Unknown exception.")
        # In most cases pass and try again will fix it. This isn't correct Python but it seems to work.
        if always_retry_after_any_exception:
            status_neopixel.fill(color[1])
            gc.collect()
            time.sleep(10)
            wifi.reset()
            pass
        else:
            exit(1)
