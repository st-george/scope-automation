#!/usr/bin/python

#import sys
#import select
import readchar
import serial
from time import localtime, strftime, time
import os
import scipy.ndimage
import numpy as np
import numpy.fft
import subprocess
import math
import psutil

ARDUINO_PORT = "/dev/tty.usbmodem1421"
ARDUINO_SPEED = "115200"

CAMERA = None
CAMERA_PORT = None
DELTA = 40
REFERENCE_FFT_RESULT = None
Z_POSITION = 0
GPHOTO2_BIN = "/usr/local/bin/gphoto2"

CORRELATIONS = {}
CORRELATIONS_RESETED = None
CORRELATIONS_RESET_DELTA = 60 * 15 # reset correlations after 15 minutes

def log(msg):
  print "[{time}] {msg}".format(time=strftime("%Y-%m-%d %H:%M:%S", localtime()), msg=msg)

# needed on OS X
def kill_ptpcamera():
  for proc in psutil.process_iter():
    if proc.name() == "PTPCamera":
      log("Killing {name} process {pid} which prevents gphoto2 from working".format(name=proc.name(),
                                                                                      pid=proc.pid))
      proc.kill()

def sample_and_fft(fname):
  img = scipy.ndimage.imread(fname, True)
  res = None
  for i in xrange(0, img.shape[0], DELTA):
    vec = np.absolute(numpy.fft.fft(img[:][i].flatten()))**2
    if res is None:
      res = vec
    else:
      res = np.concatenate([res, vec])
  return res

def capture_image_filename():
  return "data/image-{count}.%C".format(count=math.trunc(time() * 1000))

def reset_correlations(force=False):
  global CORRELATIONS, CORRELATIONS_RESETED
  if force or CORRELATIONS_RESETED is None or time() - CORRELATIONS_RESETED > CORRELATIONS_RESET_DELTA:
    log("Correlations reseted")
    CORRELATIONS = {}
    CORRELATIONS_RESETED = time()

def capture_image(use_as_reference=False):
  global REFERENCE_FFT_RESULT, Z_POSITION, CORRELATIONS, CORRELATIONS_RESETED
  fname = capture_image_filename()
  out = subprocess.check_output([ 
    GPHOTO2_BIN,
    "--port", CAMERA_PORT, 
    "--capture-image-and-download", 
    "--quiet",
    "--filename", fname])

  jpeg_fname = fname.replace("%C", "jpg")
  fft_result = sample_and_fft(jpeg_fname)

  if use_as_reference or REFERENCE_FFT_RESULT is None:
    log("Captured image {fname}, used as reference image".format(fname=jpeg_fname))
    REFERENCE_FFT_RESULT = fft_result
    reset_correlations(force=True)
  else:
    reset_correlations()
    corr = np.corrcoef(REFERENCE_FFT_RESULT, fft_result)[1,0]
    CORRELATIONS[Z_POSITION] = corr
    log("Captured image {fname}, correlation {corr}".format(fname=jpeg_fname, corr=corr))

  return jpeg_fname

def connect_arduino(ser):
  data = serial_readline(ser)
  if data != "HELLO":
    raise Exception("Expected HELLO, but got {data}".format(data=data))
  
def connect_camera():
  global CAMERA, CAMERA_PORT
  if not os.path.exists(GPHOTO2_BIN):
    raise Exception("gphoto2 binary does not exist at {path}".format(path=GPHOTO2_BIN))

  p = subprocess.Popen([GPHOTO2_BIN, "--auto-detect"], stdout=subprocess.PIPE)
  out, err = p.communicate()
  lines = out.splitlines()

  if 'Model' not in lines[0]:
    raise Exception("Unexpected output from gphoto2 --auto-detect")

  if '----' not in lines[1]:
    raise Exception("Unexpected output from gphoto2 --auto-detect")

  if len(lines) != 3:
    raise Exception("Only exactly one camera is now supported")

  CAMERA = lines[2][0:30].strip()
  CAMERA_PORT = lines[2][31:]

  log("Found camera {camera} on port {port}".format(camera=CAMERA, port=CAMERA_PORT))

def ready():
  log("Ready, q = -1, a = +1, z = capture image, r = capture image and use as reference, Ctrl-C = quit")

def setup():
  ser = serial.Serial(ARDUINO_PORT, baudrate=ARDUINO_SPEED)
  return ser

def getchar():
  #i, o, e = select.select([sys.stdin], [], [], 10)

  char = readchar.readchar()

  if char == '\x03':
    raise KeyboardInterrupt
  elif char == '\x04':
    raise EOFError
  elif char == '\x1a':
    os.kill(0, signal.SIGTSTP)
  return char

def serial_writeline(ser, data):
  log("ARDUINO -> {data}".format(data=data))
  ser.write("{data}\r\n".format(data=data));

def serial_readline(ser):
  data = ser.readline()[:-2]
  if data:
    log("ARDUINO <- {data}".format(data=data))
  return data

def move_z(ser, value):
  global Z_POSITION
  Z_POSITION += value
  serial_writeline(ser, 1)
  log("Z: {z}".format(z=Z_POSITION))

def focus():
  pass

def main():
  ser = setup()

  kill_ptpcamera()
  connect_camera()

  connect_arduino(ser)

  while True:
    ready()
    ch = getchar()
    if ch == 'q':
      move_z(ser, -1)
    elif ch == 'a':
      move_z(ser, 1)
    elif ch == 'z':
      capture_image()
    elif ch == 'r':
      capture_image(use_as_reference=True)

main()
