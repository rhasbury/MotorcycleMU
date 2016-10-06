# -*- coding: utf-8 -*-
from sensor import sensor
import curses


mySensor = sensor()
mySensor.start()


screen = curses.initscr()
# turn off input echoing
curses.noecho()
# respond to keys immediately (don't wait for enter)
curses.cbreak()
# map arrow keys to special values
screen.keypad(True)




try:

    cycling = True
    while cycling:

        s = '|roll: ' + str(mySensor.roll)
        s += '|pitch: ' + str(mySensor.pitch)
        s += '|yaw: ' + str(mySensor.yaw)
        screen.clear()
        screen.addstr(1, 1, 'Press any button to stop')
        screen.addstr(2, 2, s)
        #timeout in millis
        screen.timeout(500)
        #getch returns -1 if timeout
        res = screen.getch()

        if res is not -1:
            cycling = False

finally:
    # shut down cleanly
    #

    curses.nocbreak()
    screen.keypad(0)
    curses.echo()
    #here the sensor stops to collect data
    mySensor.stop()
    curses.endwin()
