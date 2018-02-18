#!/usr/bin/env python

import serial
import time
from serial.serialutil import SerialException 
import io

ARDUINO_PORT = "/dev/tty.usbmodem14111"
ARDUINO_SPEED = "115200"

class Error(Exception):
    """Base class for exceptions in this module."""
    pass

class PeripheralStatusError(Error):
    """Exception raised for errors related to the status of peripherals

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message

class SystemError(Error):
    """Exception raised for system errors when executing this script

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message

def connect_arduino(ser):
  data = serial_readline(ser)
  if data != "HELLO":
    raise SystemError("Expected HELLO, but got {data}".format(data=data))
  
def setup():
  try:
    ser = serial.Serial(ARDUINO_PORT, baudrate=ARDUINO_SPEED)
  except SerialException as err:
    raise PeripheralStatusError("Could not connect to Arduino: " + err.strerror)

  return ser

def serial_writeline(ser, data):
  ser.write("{data}\r\n".format(data=data));

def serial_readline(ser):
  data = ser.readline()[:-2]
  return data

def main():
  try:
    ser = setup()
    connect_arduino(ser)
    print "Turning 50 steps forward\n"
    serial_writeline(ser, "50");
    print "Sleeping 5 seconds\n"
    time.sleep(5)
    print "Turning 25 steps backward\n"
    serial_writeline(ser, "-25");
  except Error as err:
    print err


main()
