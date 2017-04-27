# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import, unicode_literals, division
import tempfile
import threading
import os

import tkinter as tk
from ginga.util import catalog, dp, wcs
from ginga.canvas.types.all import (Path, Polygon,
                                    CompoundObject)
from astropy import units as u
from astropy.coordinates import SkyCoord, Angle
from astropy.coordinates.name_resolve import NameResolveError
from astropy.vo.client import conesearch

import hcam_drivers.utils.widgets as w
from hcam_drivers.utils import get_root

# Image Archives
image_archives = [('ESO', 'eso', catalog.ImageServer,
                  "http://archive.eso.org/dss/dss?ra=%(ra)s&dec=%(dec)s&mime-type=application/x-fits&x=%(width)s&y=%(height)s",
                   "ESO DSS archive"),
                  ]


@u.quantity_input(px_val=u.pix)
@u.quantity_input(px_scale=u.arcsec/u.pix)
def _px_deg(px_val, px_scale):
    """
    convert from pixels to degrees
    """
    return px_val.to(
        u.deg,
        equivalencies=u.pixel_scale(px_scale)
    ).value


class CCDWin(Polygon):
    def __init__(self, ra_ll_deg, dec_ll_deg, xs, ys,
                 image, **params):
        """
        Shape for drawing ccd window

        Parameters
        ----------
        ra_ll_deg : float
            lower left coordinate in ra (deg)
        dec_ll_deg : float
            lower left y coord in dec (deg)
        xs : float
            x size in degrees
        ys : float
            y size in degrees
        image : `~ginga.AstroImage`
            image to plot Window on
        """
        points_wcs = (
            (ra_ll_deg, dec_ll_deg),
            wcs.add_offset_radec(ra_ll_deg, dec_ll_deg, xs, 0.0),
            wcs.add_offset_radec(ra_ll_deg, dec_ll_deg, xs, ys),
            wcs.add_offset_radec(ra_ll_deg, dec_ll_deg, 0.0, ys)
        )
        self.points = [image.radectopix(ra, dec) for (ra, dec) in points_wcs]
        super(CCDWin, self).__init__(self.points, **params)


class Sexagesimal(tk.Frame):
    def __init__(self, master, callback=None, unit='hms'):
        """
        Class to enter sexagesimal values. value function returns degrees
        """
        super(Sexagesimal, self).__init__(master, pady=2)
        if unit == 'hms':
            self.unit = u.hourangle
            self.widgets = [w.RangedInt(self, 0, 0, 23, callback, True, width=2),
                            w.RangedInt(self, 0, 0, 59, callback, True, width=2),
                            w.RangedFloat(self, 0.0, 0.0, 59.999, callback, False,
                                          width=6)]
        else:
            self.unit = u.deg
            self.widgets = [w.RangedInt(self, 0, -89, 89, callback, True, width=2),
                            w.RangedInt(self, 0, 0, 59, callback, True, width=2),
                            w.RangedFloat(self, 0.0, 0.0, 59.999, callback, False,
                                          width=6)]
        row = 0
        col = 0
        for nw, widget in enumerate(self.widgets):
            widget.grid(row=row, column=col, sticky=tk.W)
            col += 1
            if nw != len(self.widgets) - 1:
                tk.Label(self, text=':').grid(row=row, column=col, sticky=tk.W)
            col += 1

    def value(self):
        string = ':'.join((str(w.value()) for w in self.widgets))
        angle = Angle(string, unit=self.unit)
        return angle.to(u.deg).value

    def as_string(self):
        return ':'.join((str(w.value()) for w in self.widgets))

    def set(self, value):
        angle = Angle(value, unit=u.deg).to(self.unit)
        string = angle.to_string(sep=':')
        fields = string.split(':')
        for field, widget in zip(fields, self.widgets):
            widget.set(field)


class FovSetter(tk.LabelFrame):

    def __init__(self, master, fitsimage, canvas, logger):
        """
        fitsimage is reverence to ImageViewCanvas
        """
        super(FovSetter, self).__init__(master, pady=2,
                                        text='Object')

        g = get_root(self).globals
        self.set_telins(g)

        row = 0
        column = 0
        tk.Label(self, text='Object Name').grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text='or Coords').grid(row=row, column=column, sticky=tk.W)

        row += 2
        tk.Label(self, text='Tel. RA').grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text='Tel. Dec').grid(row=row, column=column, sticky=tk.W)

        row += 1
        tk.Label(self, text='Tel. PA').grid(row=row, column=column, sticky=tk.W)

        # spacer
        column += 1
        tk.Label(self, text=' ').grid(row=0, column=column)

        row = 0
        column += 1
        self.targName = w.TextEntry(self, 22)
        self.targName.grid(row=row, column=column, sticky=tk.W)

        row += 1
        self.targCoords = w.TextEntry(self, 22)
        self.targCoords.grid(row=row, column=column, sticky=tk.W)

        row += 1
        self.launchButton = tk.Button(self, width=8, fg='black',
                                      text='Load Image', bg=g.COL['main'],
                                      command=self.set_and_load)
        self.launchButton.grid(row=row, column=column, sticky=tk.W)

        row += 1
        self.ra = Sexagesimal(self, callback=self.update_info_cb, unit='hms')
        self.ra.grid(row=row, column=column, sticky=tk.W)

        row += 1
        self.dec = Sexagesimal(self, callback=self.update_info_cb, unit='dms')
        self.dec.grid(row=row, column=column, sticky=tk.W)

        row += 1
        self.pa = w.RangedFloat(self, 0.0, 0.0, 359.99, self.update_info_cb,
                                False, True, width=6)
        self.pa.grid(row=row, column=column, sticky=tk.W)

        column += 1
        row = 0
        self.query = tk.Button(self, width=12, fg='black', bg=g.COL['main'],
                               text='Query Simbad', command=self.query_simbad)
        self.query.grid(row=row, column=column, sticky=tk.W)

        self.fitsimage = fitsimage
        self.imfilepath = None
        self.logger = logger

        # Add our image servers
        self.bank = catalog.ServerBank(self.logger)
        for (longname, shortname, klass, url, description) in image_archives:
            obj = klass(self.logger, longname, shortname, url, description)
            self.bank.addImageServer(obj)
        self.servername = 'eso'
        self.tmpdir = tempfile.mkdtemp()

        # catalog servers
        for longname in conesearch.list_catalogs():
            shortname = longname
            url = ""    # astropy conesearch doesn't need URL
            description = longname
            obj = catalog.AstroPyCatalogServer(logger, longname, shortname,
                                               url, description)
            self.bank.addCatalogServer(obj)

        # canvas that we will draw on
        self.canvas = canvas

    def set_telins(self, g):
        telins = g.cpars['telins_name']
        self.px_scale = g.cpars[telins]['px_scale'] * u.arcsec/u.pix
        self.nxtot = g.cpars[telins]['nxtot'] * u.pix
        self.nytot = g.cpars[telins]['nytot'] * u.pix
        self.fov_x = _px_deg(self.nxtot, self.px_scale)
        self.fov_y = _px_deg(self.nytot, self.px_scale)

        # rotator centre position in pixels
        self.rotcen_x = g.cpars[telins]['rotcen_x'] * u.pix
        self.rotcen_y = g.cpars[telins]['rotcen_y'] * u.pix
        # is image flipped E-W?
        self.flipEW = g.cpars[telins]['flipEW']
        # does increasing PA rotate towards east from north?
        self.EofN = g.cpars[telins]['EofN']
        # rotator position in degrees when chip runs N-S
        self.paOff = g.cpars[telins]['paOff']

    @property
    def ctr_ra_deg(self):
        return self.ra.value()

    @property
    def ctr_dec_deg(self):
        return self.dec.value()

    def query_simbad(self):
        g = get_root(self).globals
        try:
            coo = SkyCoord.from_name(self.targName.value())
        except NameResolveError:
            self.targName.config(bg='red')
            self.logger.warn(msg='Could not resolve target')
            return
        self.targName.config(bg=g.COL['main'])
        self.targCoords.set(coo.to_string(style='hmsdms', sep=':'))

    def update_info_cb(self, *args):
        self.draw_ccd(*args)

    def _chip_cen(self):
        """
        return chip centre in ra, dec
        """
        xoff_hpix = (self.nxtot/2 - self.rotcen_x)
        yoff_hpix = (self.nytot/2 - self.rotcen_y)
        yoff_deg = _px_deg(yoff_hpix, self.px_scale)
        xoff_deg = _px_deg(xoff_hpix, self.px_scale)

        if not self.flipEW:
            xoff_deg *= -1

        return wcs.add_offset_radec(self.ctr_ra_deg, self.ctr_dec_deg,
                                    xoff_deg, yoff_deg)

    def _make_win(self, xs, ys, nx, ny, image, **params):
        """
        Make a canvas object to represent a CCD window

        Parameters
        ----------
        xs, ys, nx, ny : float
            xstart, ystart and size in instr pixels
        image : `~ginga.AstroImage`
            image reference for calculating scales
        params : dict
            parameters passed straight through to canvas object
        Returns
        -------
        win : `~ginga.canvas.CompoundObject`
            ginga canvas object to draw on FoV
        """
        # need bottom left coord and xy size of window in degrees
        # offset of bottom left coord window from chip ctr in degrees
        xoff_hpix = (xs*u.pix - self.rotcen_x)
        yoff_hpix = (ys*u.pix - self.rotcen_y)
        yoff_deg = _px_deg(yoff_hpix, self.px_scale)
        xoff_deg = _px_deg(xoff_hpix, self.px_scale)

        if not self.flipEW:
            xoff_deg *= -1

        ll_ra, ll_dec = wcs.add_offset_radec(self.ctr_ra_deg, self.ctr_dec_deg,
                                             xoff_deg, yoff_deg)
        xsize_deg = _px_deg(nx*u.pix, self.px_scale)
        ysize_deg = _px_deg(ny*u.pix, self.px_scale)
        if not self.flipEW:
            xsize_deg *= -1
        return CCDWin(ll_ra, ll_dec, xsize_deg, ysize_deg, image, **params)

    def _make_ccd(self, image):
        """
        Converts the current instrument settings to a ginga canvas object
        """
        # get window pair object from top widget
        g = get_root(self).globals
        wframe = g.ipars.wframe

        # all values in pixel coords of the FITS frame
        # get centre
        ctr_x, ctr_y = image.radectopix(self.ctr_ra_deg, self.ctr_dec_deg)
        self.ctr_x, self.ctr_y = ctr_x, ctr_y

        nx, ny = self.nxtot.value, self.nytot.value
        mainCCD = self._make_win(0, 0, nx, ny, image,
                                 fill=True, fillcolor='blue',
                                 fillalpha=0.3)

        # dashed lines to mark quadrants of CCD
        chip_ctr_ra, chip_ctr_dec = self._chip_cen()
        xright, ytop = wcs.add_offset_radec(chip_ctr_ra, chip_ctr_dec,
                                            self.fov_x/2, self.fov_y/2)
        xleft, ybot = wcs.add_offset_radec(chip_ctr_ra, chip_ctr_dec,
                                           -self.fov_x/2, -self.fov_y/2)
        points = (image.radectopix(ra, dec) for (ra, dec) in (
            (chip_ctr_ra, ybot), (chip_ctr_ra, ytop)
        ))
        hline = Path(points, color='red', linestyle='dash', linewidth=2)
        points = (image.radectopix(ra, dec) for (ra, dec) in (
            (xleft, chip_ctr_dec), (xright, chip_ctr_dec)
        ))
        vline = Path(points, color='red', linestyle='dash', linewidth=2)

        # list of objects for compound object
        l = [mainCCD, hline, vline]

        # iterate over window pairs
        # these coords in ccd pixel vaues
        params = dict(fill=True, fillcolor='red', fillalpha=0.3)
        if not g.ipars.isFF():
            if g.ipars.isDrift():
                for xsl, xsr, ys, nx, ny in wframe:
                    l.append(self._make_win(xsl, ys, nx, ny, image, **params))
                    l.append(self._make_win(xsr, ys, nx, ny, image, **params))
            else:
                for xsll, xsul, xslr, xsur, ys, nx, ny in wframe:
                    l.append(self._make_win(xsll, ys, nx, ny, image, **params))
                    l.append(self._make_win(xsul, 1024-ys, nx, -ny, image, **params))
                    l.append(self._make_win(xslr, ys, nx, ny, image, **params))
                    l.append(self._make_win(xsur, 1024-ys, nx, -ny, image, **params))

        obj = CompoundObject(*l)
        obj.editable = True
        return obj

    def draw_ccd(self, *args):
        image = self.fitsimage.get_image()
        if image is None:
            return
        try:
            obj = self._make_ccd(image)
            pa = self.pa.value() - self.paOff
            if not self.EofN:
                pa *= -1
            self.canvas.deleteObjectByTag('ccd_overlay')
            self.canvas.add(obj, tag='ccd_overlay', redraw=False)
            # rotate
            obj.rotate(pa, self.ctr_x, self.ctr_y)

            self.canvas.update_canvas()

        except Exception as err:
            errmsg = "failed to draw CCD: {}".format(str(err))
            self.logger.error(msg=errmsg)

    def create_blank_image(self):
        self.fitsimage.onscreen_message("Creating blank field...",
                                        delay=1.0)
        image = dp.create_blank_image(self.ctr_ra_deg, self.ctr_dec_deg,
                                      2*self.fov,
                                      0.000047, 0.0,
                                      cdbase=[-1, 1],
                                      logger=self.logger)
        image.set(nothumb=True)
        self.fitsimage.set_image(image)

    def set_and_load(self):
        coo = SkyCoord(self.targCoords.value(),
                       unit=(u.hour, u.deg))
        self.ra.set(coo.ra.deg)
        self.dec.set(coo.dec.deg)
        self.load_image()

    def load_image(self):
        self.fitsimage.onscreen_message("Getting image; please wait...")
        # offload to non-GUI thread to keep viewer somewhat responsive?
        t = threading.Thread(target=self._load_image)
        t.daemon = True
        self.logger.debug(msg='starting image download')
        t.start()
        self.after(1000, self._check_image_load, t)

    def _check_image_load(self, t):
        if t.isAlive():
            self.logger.debug(msg='checking if image has arrrived')
            self.after(500, self._check_image_load, t)
        else:
            # load image into viewer
            try:
                get_root(self).load_file(self.imfilepath)
            except Exception as err:
                errmsg = "failed to load file {}: {}".format(
                    self.imfilepath,
                    str(err)
                )
                self.logger.error(msg=errmsg)
                return
            finally:
                self.draw_ccd()
                self.fitsimage.onscreen_message(None)

    def _load_image(self):
        try:
            fov_deg = 2*max(self.fov_x, self.fov_y)
            ra_txt = self.ra.as_string()
            dec_txt = self.dec.as_string()
            # width and height are specified in arcmin
            wd = 60*fov_deg
            ht = 60*fov_deg

            # these are the params to DSS
            params = dict(ra=ra_txt, dec=dec_txt, width=wd, height=ht)

            # query server and download file
            filename = 'sky.fits'
            filepath = os.path.join(self.tmpdir, filename)
            if os.path.exists(filepath):
                os.unlink(filepath)

            dstpath = self.bank.getImage(self.servername, filepath, **params)
        except Exception as err:
            errmsg = "Failed to download sky image: {}".format(str(err))
            self.logger.error(msg=errmsg)
            return

        self.imfilepath = dstpath
