
import os
#from builtins import None
#os.system("export QUICK2WIRE_API_HOME=~/temperature/quick2wire-python-api")
#os.system("export PYTHONPATH=$PYTHONPATH:$QUICK2WIRE_API_HOME")
#os.system("export MPU6050_PATH=~/temperature/MPU6050")
#os.system("export PYTHONPATH=$PYTHONPATH:$MPU6050_PATH")
import logging
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='./MotorcycleMU.log', level=logging.DEBUG)
import datetime
import pymysql.cursors
import RPi.GPIO as GPIO
import time
from time import mktime
from datetime import timedelta
import threading 
import sys
import dateutil.parser
import math
import signal
#import Adafruit_BMP.BMP085 as BMP085
import collections
import colorsys

from gps3.agps3threaded import AGPS3mechanism


from lib_oled96 import ssd1306
from smbus import SMBus
from PIL import ImageFont, ImageDraw
#font = ImageFont.load_default()
font = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 10)
font15 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf', 15)
font20 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 20)
font30 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 30)
i2cbus = SMBus(1)        # 1 = Raspberry Pi but NOT early REV1 board
try:
    oled = ssd1306(i2cbus)   # create oled object, nominating the correct I2C bus, default address
except:
    oled = None


from i2clibraries import i2c_lcd
from max6675 import *
#from gps import *
from MPU6050 import sensor


from neopixel import *
# LED strip configuration:
LED_COUNT      = 12       # Number of LED pixels.
LED_PIN        = 18      # GPIO pin connected to the pixels (must support PWM!).
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 5       # DMA channel to use for generating signal (try 5)
LED_BRIGHTNESS = 50     # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)

strip = None

#signal.signal(signal.SIGINT, signal_handler)

logradius = 0.0001 # lattitude/long must change by this value to be saved to mysql
cs_pin = 22
clock_pin = 27
data_pin = 17
units = "c"
thermocouple = MAX6675(cs_pin, clock_pin, data_pin, units)
EngineTemp = 0; 
AmbientTemp = 0

oldlong = 0 
oldlat = 0 

oldktemp = 0
tempqlen = 10
ktempq = collections.deque(maxlen=tempqlen)


lcdline1 = "alt"
lcdline2 = "spd"
lcdline3 = "time"

i2cLock = threading.Lock()


gpsd = None #seting the global variable
gpsp = None #
tmp = None
lcd = None


def signal_quitting(signal, frame):
    global gpsp
    logging.info("Received Sigint, killing threads and waiting for join. ")
    
    gpsp.running = False
    tempthread.running = False
    lcdthread.running = False
    
    ninedof.stop()
    
    gpsp.join(2) # wait for the thread to finish what it's doing
    logging.info("gps thread killed, quitting")
    lcdthread.join(2)
    logging.info("lcd update thread killed, quitting")
    tempthread.join(2)
    logging.info("temperature updating thread killed, quitting")
    logging.info("all threads killed, quitting")
    logging.info('You pressed Ctrl+C!')    
    sys.exit(0)    


def logTemplineDB(location, temp):    
    try:
        connection = pymysql.connect(host='localhost', user='monitor', passwd='password', db='temps', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
        with connection.cursor() as cursor:
            cursor.execute ("INSERT INTO tempdat values(NOW(), %s, %s)", (location, temp))
        connection.commit()
        logging.debug("logTempLineDB() Rows logged: %s" % cursor.rowcount)
        connection.close()
    except:
        logging.error("logTempLineDB Temperature Logging exception Error ", exc_info=True)



def UpdateTemps():
    global EngineTemp
    global AmbientTemp
    global lcdline1
    global lcdline2
    global lcdline3    
    global tmp
    global oldktemp
    global strip
    
    tmp = None
#     i2cLock.acquire()
#     try:        
#         tmp = BMP085.BMP085()        
#         AmbientTemp = tmp.read_temperature()
#         logTemplineDB("ambient", AmbientTemp)
#     except:
#         tmp = None
#         logging.error("UpdateTemps() Ambient Temp Read Error: ", exc_info=True)
#     finally:
#         i2cLock.release()
    AmbientTemp = 99

    try:
        EngineTemp = thermocouple.get()
        #if(EngineTemp < 200 ):                  # check to remove unrealistic measurement...which happen frequently due to engine noise.              
            #ktempq.append(EngineTemp)            
            #qavg = sum(ktempq) / ktempq.__len__()
            #if(abs(EngineTemp-qavg) < 10):
                #logTemplineDB("engine", EngineTemp)
        lcdline1 = "E:%4.1fC A:%4.1fC" % (EngineTemp, AmbientTemp)  
    except KeyboardInterrupt:                        
        raise   
    except MAX6675Error as e:
        #EngineTemp = "Error: "+ e.value
        EngineTemp = -10
        logging.error("UpdateTemps() Excepted getting enginetemp: ", exc_info=True)
    
    if(ninedof != None):
        i2cLock.acquire()
        try:
            roll = ninedof.roll
            #lcdline3 = "Roll: %4.1f " % (ninedof.roll)
            roll = roll + 90
            charposition = round(abs(roll/12)) 
            s = "              "
            if (charposition < 15) :
                lcdline3 = s[:charposition] + 'O' + s[charposition:]
    
        except:
            logging.error("UpdateTemps() ninedof sensor couldn't be read", exc_info=True)
        
        finally:
            i2cLock.release()
    
    if(strip != None):
        
        colour = IntegertoRGB(EngineTemp-80)
        strip.setPixelColorRGB(0, int(colour[0]*255), int(colour[1]*255), int(colour[2]*255))        
        colour = IntegertoRGB(AmbientTemp-25)
        strip.setPixelColorRGB(1, int(colour[0]*255), int(colour[1]*255), int(colour[2]*255))
        strip.show()
        #logging.error("changed LEDs")
        
    
    #print (lcdstring)



def LogGPSPoint():
    global gpsd
    global EngineTemp
    global AmbientTemp
    global lcdline1
    global lcdline2   
    global lcdline3
    global logradius
    resp = ""
   
    global oldlat
    global oldlong
   
    try:
        con = pymysql.connect(host='localhost', user='monitor', passwd='password', db='gps', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
        cur = con.cursor()
    except KeyboardInterrupt:                        
        raise
    except:
        logging.error("LogGPSPoint: Error opening MySQL connection ", exc_info=True)
        sys.exit(1)
        
    try:    
        if(agps_thread.data_stream.mode == 3):
            gtime = dateutil.parser.parse(agps_thread.data_stream.time) - timedelta(hours=4)
            logging.debug("difference in old points {0}, {1} ".format(abs(oldlat - agps_thread.data_stream.lat), abs(oldlong - agps_thread.data_stream.lon)))
            if(abs(oldlat - agps_thread.data_stream.lat) > logradius or abs(oldlong - agps_thread.data_stream.lon) > logradius):                 
                #print ('time utc    ' , gpsd.utc)
                #print ('time utc    ' , agps_thread.data_stream.time)                
                sql = "insert into gps(n_lat, w_long, date_time, fix_time, speed, altitude, mode, track, climb, enginetemp, ambienttemp, satellites) values(%s, %s, NOW(), FROM_UNIXTIME(%s), %s, %s, %s, %s, %s, %s, %s, %s)" % (agps_thread.data_stream.lat, 
                                                                                                                                                                                                                                  agps_thread.data_stream.lon, 
                                                                                                                                                                                                                                  mktime(gtime.timetuple()), 
                                                                                                                                                                                                                                  agps_thread.data_stream.speed, 
                                                                                                                                                                                                                                  agps_thread.data_stream.alt, 
                                                                                                                                                                                                                                  agps_thread.data_stream.mode, 
                                                                                                                                                                                                                                  agps_thread.data_stream.track, 
                                                                                                                                                                                                                                  agps_thread.data_stream.climb, 
                                                                                                                                                                                                                                  EngineTemp, 
                                                                                                                                                                                                                                  AmbientTemp, 
                                                                                                                                                                                                                                  len(agps_thread.data_stream.satellites))
                sql = sql.replace("nan", "-9999")
                cur.execute(sql)
                con.commit()                
                oldlat = agps_thread.data_stream.lat
                oldlong = agps_thread.data_stream.lon
                logging.debug("Rows inserted: %s" % cur.rowcount)
                logging.debug("SQL String: %s" % sql)
            
            lcdline1 = "{: >4.1f} m".format(agps_thread.data_stream.altitude)
            lcdline2 = "{: >4.1f} km".format(agps_thread.data_stream.speed * 3.6)
            lcdline3 = gtime.strftime('%I:%M')
        elif(agps_thread.data_stream.mode != 3):
            lcdline1 = "  "
            lcdline2 = "NoFix"
            lcdline3 = "  "

            sql = "insert into gps(n_lat, w_long, date_time, fix_time, speed, altitude, mode, track, climb, enginetemp, ambienttemp, satellites) values(%s, %s, NOW(), FROM_UNIXTIME(%s), %s, %s, %s, %s, %s, %s, %s)" % (agps_thread.data_stream.lat, 
                                                                                                                                                                                                                                  agps_thread.data_stream.lon,                                                                                                                                                                                                                                   
                                                                                                                                                                                                                                  agps_thread.data_stream.speed, 
                                                                                                                                                                                                                                  agps_thread.data_stream.alt, 
                                                                                                                                                                                                                                  agps_thread.data_stream.mode, 
                                                                                                                                                                                                                                  agps_thread.data_stream.track, 
                                                                                                                                                                                                                                  agps_thread.data_stream.climb, 
                                                                                                                                                                                                                                  EngineTemp, 
                                                                                                                                                                                                                                  AmbientTemp, 
                                                                                                                                                                                                                                 len(agps_thread.data_stream.satellites))
            print(sql)
            logging.debug(sql)
    except KeyboardInterrupt:                        
        raise
    except:
        #print (sys.exc_info()[0])
        logging.error("LogGPSPoint() excepted trying to log GPS data ", exc_info=True)

    finally:
        if con:
            con.close()
      
     




class GpsPoller(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.current_value = None
        self.running = True #setting the thread running to true

 
    def run(self):
        global gpsd
        global gpsp
        
        gps_connected = False
       
        while gpsp.running:
            LogGPSPoint()
            time.sleep(2)

            
#             try:
#                 gpsd = GPS(mode=WATCH_ENABLE) #starting the stream of info
#                 gps_connected = True
#             except KeyboardInterrupt:                        
#                 raise
#             except:
#                 logging.error("GPSPoller() excepted connecting to GPSD ", exc_info=True)
#                 gps_connected = False
#             
#             oldtime = time.time()
#             while(gps_connected == True):
#                 if(gpsd.waiting(3000)):                
#                     try:                        
#                         gpsd.next() #this will continue to loop and grab EACH set of gpsd info to clear the buffer
#                         logging.debug("seconds passed since last GPS sentence: %s", (time.time() - oldtime))
#                         if(time.time() - oldtime > 2):                            
#                             oldtime = time.time()
#                             LogGPSPoint()                        
#                     except JsonError:
#                         logging.error("run() -> gpsd.next() threw JsonError", exc_info=True)
#                         gps_connected = False                
#                     except ValueError:
#                         logging.error("run() -> gpsd.next() threw ValueError", exc_info=True)
#                         gps_connected = False
#                     except StopIteration:                    
#                         logging.error("run() -> gpsd.next() threw stopiteration", exc_info=True)
#                         gps_connected = False
#                     except KeyboardInterrupt:                        
#                         raise
#                 
#                 #time.sleep(0.5)
#                 
#             #time.sleep(5)
             
 
 
 
class LcdUpdate(threading.Thread):
    
    def __init__(self):
        threading.Thread.__init__(self)
        self.current_value = None
        self.running = True #setting the thread running to true 
        i2cLock.acquire()
        try:
            oled.canvas.rectangle((0, 0, oled.width-1, oled.height-1), outline=1, fill=0)
            oled.cls()
        finally:
            i2cLock.release()
        
    def run(self):
        global lcd
        global lcdline1
        global lcdline2                 
        global lcdline3
        while self.running:
                        
            if(oled != None):
                i2cLock.acquire()
                try:
                    oled.canvas.rectangle((0, 0, oled.width-1, oled.height-1), outline=1, fill=0)
                    oled.canvas.text((66,8), "E{0:3.0f}".format(EngineTemp), font=font20, fill=1)
                    oled.canvas.text((66,33), "A{0:3.0f}".format(AmbientTemp), font=font20, fill=1)
                    oled.canvas.text((8,8), lcdline2, font=font15, fill=1)
                    oled.canvas.text((8,24), lcdline1, font=font15, fill=1)
                    oled.canvas.text((8,40), lcdline3, font=font15, fill=1)
                    #print("LCDString1: %s" % lcdline1)
                    #print("LCDString2: %s" % lcdline2)
                    #print("LCDString3: %s" % lcdline3)
                    oled.display()
                finally:
                    i2cLock.release()
                    
            if(lcd != None):            
                lcdline3 = datetime.datetime.now()
                i2cLock.acquire()
                try:
                    lcd.clear
                    lcd.setPosition(1, 0) 
                    lcd.writeString(lcdline1)
                    lcd.setPosition(2, 0) 
                    lcd.writeString(lcdline2)
                    logging.debug("LCDString1: %s" % lcdline1)
                    logging.debug("LCDString2: %s" % lcdline2)
                finally:
                    i2cLock.release()
                #lcd = None
            time.sleep(0.2)            
             

 

def IntegertoRGB(numberin):    
       
    H = 1 - ((numberin/30) * 0.4)
    S = 0.9
    B = 0.9
    if (H < 0):
        H = 0
    rgb = colorsys.hsv_to_rgb(H, S, B)
    return rgb
 
class TempUpdates(threading.Thread):
    
    def __init__(self):
        threading.Thread.__init__(self)
        self.current_value = None
        self.running = True #setting the thread running to true 
        
        
    def run(self):                 
        while self.running:
            UpdateTemps()
            time.sleep(1)
            
 
 
if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='./MotorcycleMU.log', level=logging.DEBUG)
    
    
    tmp = None
    
    try:
        agps_thread = AGPS3mechanism()  # Instantiate AGPS3 Mechanisms
        agps_thread.stream_data()  # From localhost (), or other hosts, by example, (host='gps.ddns.net')
        agps_thread.run_thread()  # Throttle time to sleep after an empty lookup, default 0.2 second, default daemon=True
    
    except:
        logging.error("GPS Connection Error", exc_info=True)
        
    #try:
    #    tmp = BMP085.BMP085()
    #except:
    #    logging.error("BMP085 IO Error", exc_info=True)
    #    tmp = None

    #try:
    #    ninedof = sensor.sensor()
    #    ninedof.start()
    #except IOError:
    #    logging.error("9dof sensor init error", exc_info=True)
    #    ninedof = None
    ninedof = None
    
    
    logging.info("Logging started")
    signal.signal(signal.SIGINT, signal_quitting)
    
    # Configuration parameters
    # I2C Address, Port, Enable pin, RW pin, RS pin, Data 4 pin, Data 5 pin, Data 6 pin, Data 7 pin, Backlight pin (optional)
    i2cLock.acquire()
    try:
        lcd = i2c_lcd.i2c_lcd(0x27, 1, 2, 1, 0, 4, 5, 6, 7, 3)
        lcd.backLightOn()
    except IOError:
        logging.info("LCD (the green kind) not found on I2C", exc_info=True)
        lcd = None
    finally:
        i2cLock.release()
    
    try:
        strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
        strip.begin()
    except:
        logging.info("WS2812 LED strip/ring not found", exc_info=True)
        strip = None
    
    
    try:        
        gpsp = GpsPoller()
        gpsp.start()
        
        tempthread = TempUpdates()
        tempthread.start()
    
        #if(lcd != None):
        lcdthread = LcdUpdate()
        lcdthread.start()
        while True: time.sleep(100)
    except:
        raise    
