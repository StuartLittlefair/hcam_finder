# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import, unicode_literals, division
import pkg_resources

from tkinter import filedialog
from os.path import expanduser

# let's see which image library we have
have_pillow = True
try:
    import PIL.Image as Image
    import PIL.ImageDraw as ImageDraw
    import PIL.ImageFont as ImageFont
except:
    have_pillow = False

have_opencv = True
try:
    import cv2
except:
    have_opencv = False


def make_finder(logger, img_array, object_name, ra, dec, pa):
    """
    Make finding chart with object info overlaid
    """
    fname = filedialog.asksaveasfilename(
        initialdir=expanduser("~"),
        defaultextension='.jpg',
        filetypes=[('finding charts', '.log')],
        title='Name of finding chart')

    if have_pillow:
        make_finder_pillow(logger, fname, img_array, object_name, ra, dec, pa)
    elif have_opencv:
        make_finder_opencv(logger, fname, img_array, object_name, ra, dec, pa)
    else:
        logger.error(msg='Cannot make finder, please install openCV or Pillow')


def make_finder_opencv(logger, fname, img_array, object_name, ra, dec, pa):
    logger.error(msg="openCV finding chart saving not implemented, please install Pillow")


def make_finder_pillow(logger, fname, img_array, object_name, ra, dec, pa):
    image = Image.fromarray(img_array)
    image = image.convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)
    info_msg = "{object_name}\n{ra} {dec}\nPA = {pa:.1f}".format(
        object_name=object_name, ra=ra, dec=dec, pa=pa
    )
    font_size = 5
    font_file = pkg_resources.resource_filename('hcam_finder', 'data/Lato-Regular.ttf')
    text_x = 0.0
    while text_x/width < 0.3:
        font_size += 1
        font = ImageFont.truetype(font_file, font_size)
        text_x, text_y = max((font.getsize(txt) for txt in info_msg.splitlines()))

    rect_x, rect_y = int(1.1*text_x), int(4.0*text_y)
    rectangle = Image.new('RGBA', (rect_x, rect_y), (255, 255, 255, 200))

    width, height = image.size
    x = width - rect_x
    y = 0
    image.paste(rectangle, (x, y), rectangle)
    x = width - 1.05*text_x
    draw.text((x, y), info_msg, font=font, fill='rgb(255, 0, 0)')
    image.save(fname)