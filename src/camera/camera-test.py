import psutil

# needed on OS X
def kill_ptpcamera():
  for proc in psutil.process_iter():
    if proc.name() == "PTPCamera":
      print("Killing {name} process {pid} which prevents gphoto2 from working".format(name=proc.name(),
                                                                                      pid=proc.pid))
      proc.kill()

import gphoto2 as gp
kill_ptpcamera()
context = gp.Context()
camera = gp.Camera()
camera.init(context)
text = camera.get_summary(context)
print('Summary')
print('=======')
print(str(text))
camera.exit(context)
