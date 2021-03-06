#!/usr/bin/env python

from __future__ import print_function

import time

import io
import logging
import os
import sys
import gphoto2 as gp

def main():
    logging.basicConfig(format='%(levelname)s: %(name)s: %(message)s', level=logging.ERROR)
    gp.check_result(gp.use_python_logging())
    camera = gp.check_result(gp.gp_camera_new())
    gp.check_result(gp.gp_camera_init(camera))
    # required configuration will depend on camera type!
    print('Checking camera config')
    # get configuration tree
    config = gp.check_result(gp.gp_camera_get_config(camera))
    # find the image format config item
    OK, image_format = gp.gp_widget_get_child_by_name(config, 'imageformat')
    if OK >= gp.GP_OK:
        # get current setting
        value = gp.check_result(gp.gp_widget_get_value(image_format))
        # make sure it's not raw
        if 'raw' in value.lower():
            print('Cannot preview raw images')
            return 1
    # find the capture size class config item
    # need to set this on my Canon 350d to get preview to work at all
    OK, capture_size_class = gp.gp_widget_get_child_by_name(
        config, 'capturesizeclass')
    if OK >= gp.GP_OK:
        # set value
        value = gp.check_result(gp.gp_widget_get_choice(capture_size_class, 2))
        gp.check_result(gp.gp_widget_set_value(capture_size_class, value))
        # set config
        gp.check_result(gp.gp_camera_set_config(camera, config))
    # capture preview image (not saved to camera memory card)
    print('Capturing preview image')

    for x in xrange(1,100):
        millis = int(round(time.time() * 1000))

        camera_file = gp.check_result(gp.gp_camera_capture_preview(camera))

        print("capture %d %s\n" % (int(round(time.time() * 1000)) - millis, camera_file))

        file_data = gp.check_result(gp.gp_file_get_data_and_size(camera_file))

        print("download %d\n" % (int(round(time.time() * 1000)) - millis))

        data = memoryview(file_data)

    # display image
    #image = Image.open(io.BytesIO(file_data))
    #image.show()
    gp.check_result(gp.gp_camera_exit(camera))
    return 0

if __name__ == "__main__":
    sys.exit(main())
