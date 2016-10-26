#!/usr/bin/python3.4
# -*- coding: utf-8 -*-
import os
import logging
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='./MotorcycleMU.log', level=logging.INFO)
import socket
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
import collections
import colorsys
import Adafruit_BMP.BMP085 as BMP085
from gps3.agps3threaded import AGPS3mechanism
import Adafruit_ADS1x15

from lib_oled96 import ssd1306
from smbus import SMBus
from PIL import ImageFont, ImageDraw

from i2clibraries import i2c_lcd
from max6675 import *
#from gps import *
from MPU6050 import sensor
from neopixel import *

#font = ImageFont.load_default()
font = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 10)
font15 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf', 15)
font20 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 20)
font30 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 30)

qlen = 51
ktempq = collections.deque(maxlen=qlen)
speedq = collections.deque(maxlen=qlen)
altq = collections.deque(maxlen=qlen)

def signal_quitting(signal, frame):
    global gpsp
    logging.info("Received Sigint, killing threads and waiting for join. ")
    
    agps_thread.stop()
    
    gpsp.running = False
    tempthread.running = False
    lcdthread.running = False
    buttonwatcher.running = False
    
       
    gpsp.join(2) # wait for the thread to finish what it's doing
    logging.info("gps thread killed, quitting")
    lcdthread.join(2)
    logging.info("lcd update thread killed, quitting")
    tempthread.join(2)
    logging.info("button watcher thread killed, quitting")
    buttonwatcher.join(2)
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



class GpsPoller(threading.Thread):    
    def __init__(self):
        threading.Thread.__init__(self)
        self.current_value = None
        self.running = True #setting the thread running to true
        # GPS constants 
        self.logradius = 0.0001 # lattitude/long must change by this value to be saved to mysql
              
        self.oldlat = 0
        self.oldlong = 0
 
    def run(self):
        global gpsd
        global gpsp
        
        gps_connected = False
       
        while gpsp.running:
            self.LogGPSPoint()
            time.sleep(1)

    def LogGPSPoint(self):

     
        resp = ""
                 
        try:
            con = pymysql.connect(host='localhost', user='monitor', passwd='password', db='gps', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
            cur = con.cursor()
        except KeyboardInterrupt:                        
            raise
        except:
            logging.error("LogGPSPoint: Error opening MySQL connection ", exc_info=True)
            sys.exit(1)
            
        try:    
            print(agps_thread.data_stream.mode)
            
            if(agps_thread.data_stream.mode == 2 or agps_thread.data_stream.mode == 3):
                gtime = dateutil.parser.parse(agps_thread.data_stream.time) - timedelta(hours=4)
                logging.debug("difference in old points {0}, {1} ".format(abs(self.oldlat - agps_thread.data_stream.lat), abs(self.oldlong - agps_thread.data_stream.lon)))
                if(1): #abs(self.oldlat - agps_thread.data_stream.lat) > self.logradius or abs(self.oldlong - agps_thread.data_stream.lon) > self.logradius):                 
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
                                                                                                                                                                                                                                      ktempq[-1], 
                                                                                                                                                                                                                                      tempthread.AmbientTemp, 
                                                                                                                                                                                                                                      len(agps_thread.data_stream.satellites))
                    sql = sql.replace("nan", "-9999")
                    cur.execute(sql)
                    con.commit()                
                    self.oldlat = agps_thread.data_stream.lat
                    self.oldlong = agps_thread.data_stream.lon
                    
                    logging.info("Rows inserted: %s" % cur.rowcount)
                    logging.info("SQL String: %s" % sql)
                
                lcdthread.lcdline1 = "{: >4.1f} m".format(agps_thread.data_stream.alt)
                lcdthread.lcdline2 = "{: >4.1f} km".format(agps_thread.data_stream.speed * 3.6)
                lcdthread.lcdline3 = gtime.strftime('%I:%M')
                speedq.append(agps_thread.data_stream.speed * 3.6)
                altq.append(agps_thread.data_stream.alt)
                
            elif(agps_thread.data_stream.mode != 3):
                lcdthread.lcdline1 = "  "
                lcdthread.lcdline2 = "NoFix"
                lcdthread.lcdline3 = "  g  "

        except KeyboardInterrupt:                        
            raise
        except:
            #print (sys.exc_info()[0])
            logging.error("LogGPSPoint() excepted trying to log GPS data ", exc_info=True)
    
        finally:
            if con:
                con.close()








class ButtonWatcher(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.current_value = None
        self.running = True #setting the thread running to true
        i2cLock.acquire()
        try:
            self.adc = Adafruit_ADS1x15.ADS1115()
    
        finally:
            i2cLock.release()
            
            
        
        self.GAIN = 1 
    
    
    def run(self):
        
        released = True
        while (self.running):
                
            # Check for button press on ADC
            i2cLock.acquire()
            try:
                value = self.adc.read_adc(0, gain=self.GAIN)
            finally:
                i2cLock.release()
                
            if(value > 500 and released == True):
                lcdthread.ChangeLCDMode = True
                released = False
            
            time.sleep(0.01)
            
            if(value < 500 ):
                released = True
        
 
class LcdUpdate(threading.Thread):    
    def __init__(self):
        threading.Thread.__init__(self)
        self.current_value = None
        self.running = True #setting the thread running to true 
        
        self.LcdDisplayMode = 0    
        self.ChangeLCDMode = False
        
        self.lcdline1 = "  "
        self.lcdline2 = "NoFix"
        self.lcdline3 = "  "
        
                        
        i2cLock.acquire()
        try:
            # Configuration parameters
            # I2C Address, Port, Enable pin, RW pin, RS pin, Data 4 pin, Data 5 pin, Data 6 pin, Data 7 pin, Backlight pin (optional)
            self.lcd = i2c_lcd.i2c_lcd(0x27, 1, 2, 1, 0, 4, 5, 6, 7, 3)
            self.lcd.backLightOn()
        except IOError:
            logging.info("LCD (the green kind) not found on I2C", exc_info=True)
            self.lcd = None
        finally:
            i2cLock.release()
        
        try:
            self.oled = ssd1306(i2cbus)   # create self.oled object, nominating the correct I2C bus, default address
        except:
            logging.error("Failed to create OLED object", exc_info=True)
            self.oled = None

        
        i2cLock.acquire()
        try:
            self.oled.canvas.rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline=1, fill=0)
            self.oled.cls()
        finally:
            i2cLock.release()
        
    def run(self):        

                
        counter = 0
         
        while self.running:
            if(self.ChangeLCDMode == True):
                if(self.LcdDisplayMode == 5):
                    self.LcdDisplayMode = 0
                else:
                    self.LcdDisplayMode += 1
                time.sleep(0.2)
                self.ChangeLCDMode = False
            else:
                time.sleep(0.2)
                        
            if(self.oled != None):
                
                if(self.LcdDisplayMode == 1):                

                    x = 24 
                    self.oled.canvas.rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline=1, fill=0)
                    
                    self.oled.canvas.text((30,1),  "Engine Temp (\N{DEGREE SIGN}C)", font=font, fill=1)
                    
                    self.oled.canvas.line((25,30,128,30), width=1, fill=1)        
                    self.oled.canvas.text((3,25), "100", font=font, fill=1)
                    self.oled.canvas.line((25,48,128,48), width=1, fill=1)
                    self.oled.canvas.text((3,43), "50", font=font, fill=1)
                    self.oled.canvas.line((25,11,128,11), width=1, fill=1)
                    self.oled.canvas.text((3,6), "150", font=font, fill=1)
                    
                    
                    for i in list(ktempq):
                        x = x + 2 
                        y = 63 - int(((i-10)/170)*63) 
                        #print("x:{}  y:{}".format(x,y))                            
                        self.oled.canvas.line((x,63,x,y), width=2, fill=1)

                
                elif(self.LcdDisplayMode == 2):
                    
                    x = 24 
                    self.oled.canvas.rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline=1, fill=0)
                    
                    self.oled.canvas.text((40,1), "Speed (km/h)", font=font, fill=1)
                    
                    self.oled.canvas.line((25,30,128,30), width=1, fill=1)        
                    self.oled.canvas.text((3,25), "100", font=font, fill=1)
                    self.oled.canvas.line((25,48,128,48), width=1, fill=1)
                    self.oled.canvas.text((3,43), "50", font=font, fill=1)
                    self.oled.canvas.line((25,11,128,11), width=1, fill=1)
                    self.oled.canvas.text((3,6), "150", font=font, fill=1)
                    
                    
                    for i in list(speedq):
                        x = x + 2 
                        y = 63 - int(((i-10)/170)*63) 
                        #print("x:{}  y:{}".format(x,y))                            
                        self.oled.canvas.line((x,63,x,y), width=2, fill=1)
            
                    
                    
                elif(self.LcdDisplayMode == 3):

                    x = 24 
                    self.oled.canvas.rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline=1, fill=0)
                    
                    self.oled.canvas.text((40,1), "Altitude (m)", font=font, fill=1)
                    
                    self.oled.canvas.line((25,54,128,54), width=1, fill=1)        
                    self.oled.canvas.text((3,49), "160", font=font, fill=1)
                    self.oled.canvas.line((25,38,128,38), width=1, fill=1)
                    self.oled.canvas.text((3,33), "320", font=font, fill=1)
                    self.oled.canvas.line((25,22,128,22), width=1, fill=1)
                    self.oled.canvas.text((3,17), "480", font=font, fill=1)
                    
                    
                    for i in list(altq):
                        x = x + 2 
                        y = 63 - int(((i-70)/630)*63) 
                        #print("x:{}  y:{}".format(x,y))                            
                        self.oled.canvas.line((x,63,x,y), width=2, fill=1)
                                        
                

                elif(self.LcdDisplayMode == 4):
                    self.oled.canvas.rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline=1, fill=0)
                    if(agps_thread.data_stream.mode == 2 or agps_thread.data_stream.mode == 3):
                        gtime = dateutil.parser.parse(agps_thread.data_stream.time) - timedelta(hours=4)                        
                        self.oled.canvas.text((10,20), gtime.strftime('%I:%M'), font=font30, fill=1)
                    else:
                        self.oled.canvas.text((10,20), "No fix", font=font30, fill=1)
                        

                
                else:
                    self.oled.canvas.rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline=1, fill=0)
                    self.oled.canvas.text((66,8), "E{0:3.0f}".format(tempthread.EngineTemp), font=font20, fill=1)
                    self.oled.canvas.text((66,33), "A{0:3.0f}".format(tempthread.AmbientTemp), font=font20, fill=1)
                    self.oled.canvas.text((8,8), self.lcdline2, font=font15, fill=1)
                    self.oled.canvas.text((8,24), self.lcdline1, font=font15, fill=1)
                    self.oled.canvas.text((8,40), self.lcdline3, font=font15, fill=1)

            i2cLock.acquire()
            try:
                self.oled.display()
            finally:
                i2cLock.release()

                        
            if(self.lcd != None):            
                lcdline3 = datetime.datetime.now()
                i2cLock.acquire()
                try:
                    self.lcd.clear
                    self.lcd.setPosition(1, 0) 
                    self.lcd.writeString(self.lcdline1)
                    self.lcd.setPosition(2, 0) 
                    self.lcd.writeString(self.lcdline2)
                    logging.debug("LCDString1: %s" % self.lcdline1)
                    logging.debug("LCDString2: %s" % self.lcdline2)
                finally:
                    i2cLock.release()
            

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
        
        self.tempDbLogInterval = 100
        
        self.EngineTemp = 0; 
        self.AmbientTemp = 0
                
        # Configuration for MAX6675 temperature sensor board 
        cs_pin = 22
        clock_pin = 27
        data_pin = 17
        units = "c"
        
        try:            
            self.thermocouple = MAX6675(cs_pin, clock_pin, data_pin, units)
        except:
            logging.error("Failed to create MAX6675 thermocouple object", exc_info=True)
            self.thermocouple = None 
        
        
        # LED strip configuration:
        LED_COUNT      = 12       # Number of LED pixels.
        LED_PIN        = 18      # GPIO pin connected to the pixels (must support PWM!).
        LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
        LED_DMA        = 5       # DMA channel to use for generating signal (try 5)
        LED_BRIGHTNESS = 50     # Set to 0 for darkest and 255 for brightest
        LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)

        try:
            self.strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
            self.strip.begin()
        except:
            logging.info("WS2812 LED strip/ring not found", exc_info=True)
            self.strip = None
            
        #BMP085 configuration            
        i2cLock.acquire()    
        try:
            self.tmp = BMP085.BMP085()
        except:
            logging.error("BMP085 IO Error", exc_info=True)
            self.tmp = None
        finally:
            i2cLock.release()

        
        # nine degrees of freedom (MPU6050 sensor) configuration
        i2cLock.acquire()
        try:
            self.ninedof = sensor.sensor()
            self.ninedof.start()
        except IOError:
            logging.error("9dof sensor init error", exc_info=True)
            self.ninedof = None
        finally:
            i2cLock.release()
       
        
    def run(self):                 
        while self.running:
            self.UpdateTemps()
            time.sleep(1)
        self.ninedof.stop()

    def UpdateTemps(self):
        if(self.tmp != None):
            i2cLock.acquire()
            try:        
                self.AmbientTemp = self.tmp.read_temperature()
                logTemplineDB("ambient", self.AmbientTemp)
            except:                
                logging.error("UpdateTemps() Ambient Temp Read Error: ", exc_info=True)
            finally:
                i2cLock.release()
        else:
            self.AmbientTemp = 99
    
        try:
            self.EngineTemp = self.thermocouple.get()
            if(self.EngineTemp < 200 ):                  # check to remove unrealistic measurement...which happen frequently due to engine noise.              
                ktempq.append(self.EngineTemp)            
                qavg = sum(ktempq) / ktempq.__len__()
                #if(abs(self.EngineTemp-qavg) < 10):                    
                #    logTemplineDB("engine", self.EngineTemp)
              
        except KeyboardInterrupt:                        
            raise   
        except MAX6675Error as e:
            self.EngineTemp = -10
            logging.error("UpdateTemps() Excepted getting enginetemp: ", exc_info=True)
        
        if(self.ninedof != None):
            i2cLock.acquire()
            try:
                roll = self.ninedof.roll   
            except:
                logging.error("UpdateTemps() ninedof sensor couldn't be read", exc_info=True)
            
            finally:
                i2cLock.release()
    
                            
            #roll = roll + 90
            #print(self.ninedof.y_acc)
            x_led_pos = round(abs((self.ninedof.x_acc+10)/20)*12)
            y_led_pos = round(abs((self.ninedof.y_acc+10)/20)*12)
            z_led_pos = round(abs((self.ninedof.z_acc+10)/20)*12) 
            try:
                self.blackout(self.strip)
                if (x_led_pos < 12 and self.strip != None):                                    
                    self.strip.setPixelColorRGB(x_led_pos, 0, 255, 0)
                if (y_led_pos < 12 and self.strip != None):                                    
                    self.strip.setPixelColorRGB(y_led_pos, 255, 0, 0)
                if (z_led_pos < 12 and self.strip != None):                                    
                    self.strip.setPixelColorRGB(z_led_pos, 0, 0, 255)
                    
                self.strip.show()
            except:
                logging.error("UpdateTemps() couldn't write to led strip", exc_info=True)
    
    
        
        #if(strip != None):
            
            #colour = IntegertoRGB(EngineTemp-80)
            #strip.setPixelColorRGB(0, int(colour[0]*255), int(colour[1]*255), int(colour[2]*255))        
            #colour = IntegertoRGB(AmbientTemp-25)
            #strip.setPixelColorRGB(1, int(colour[0]*255), int(colour[1]*255), int(colour[2]*255))
            #strip.show()
            #logging.error("changed LEDs")
    
    
    
    def blackout(self, strip):
        for i in range(max(strip.numPixels(), strip.numPixels())):
            strip.setPixelColor(i, Color(0,0,0))
            strip.show()


            

def get_lock(process_name):
    # Without holding a reference to our socket somewhere it gets garbage
    # collected when the function exits
    get_lock._lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    try:
        get_lock._lock_socket.bind('\0' + process_name)
        logging.info("Created lock for process")
    except socket.error:
        logging.info("Lock exists. Process is already running")
        print("Lock exists. Process is already running")
        sys.exit()

 
if __name__ == "__main__":
    #logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='./MotorcycleMU.log', level=logging.INFO)
        
    get_lock('motorcyclemu')
     
    i2cLock = threading.Lock()    
    i2cbus = SMBus(1)        
   
    try:
        agps_thread = AGPS3mechanism()  # Instantiate AGPS3 Mechanisms
        agps_thread.stream_data()  # From localhost (), or other hosts, by example, (host='gps.ddns.net')
        agps_thread.run_thread()  # Throttle time to sleep after an empty lookup, default 0.2 second, default daemon=True    

        
    except:
        logging.error("Error creating GPS objects or data stream", exc_info=True)


    logging.info("Logging started")
    signal.signal(signal.SIGINT, signal_quitting)
    
    
    try:       
        lcdthread = LcdUpdate()
        tempthread = TempUpdates()
        gpsp = GpsPoller()
        buttonwatcher = ButtonWatcher()
        
        
        tempthread.start()
        gpsp.start()
        lcdthread.start()
        buttonwatcher.start()



        while True: time.sleep(100)
    except:
        raise    
