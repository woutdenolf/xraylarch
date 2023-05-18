#!/usr/bin/env pythonw
'''
GUI for displaying 1D XRD images

'''
import os
from os.path import expanduser

import numpy as np
from numpy.polynomial.chebyshev import chebfit
import sys
import time
import re
import math

from threading import Thread
from functools import partial

import wx
import wx.lib.scrolledpanel as scrolled
from wxmplot import PlotPanel

import larch
from larch.larchlib import read_workdir, save_workdir
from larch.utils import nativepath, get_cwd
from larch.utils.physical_constants import PLANCK_HC
from larch.xray import XrayBackground
from larch.xrd import (cifDB, SearchCIFdb, QSTEP, QMIN, QMAX, CATEGORIES,
                       match_database, d_from_q,twth_from_q,q_from_twth,
                       d_from_twth,twth_from_d,q_from_d, lambda_from_E,
                       E_from_lambda,calc_broadening,
                       instrumental_fit_uvw,peaklocater,peakfitter,
                       xrd1d, peakfinder_methods,SPACEGROUPS, create_xrdcif,
                       save1D)


from larch.wxlib import (ReportFrame, BitmapButton, FloatCtrl, FloatSpin,
                         SetTip, GridPanel, get_icon, SimpleText, pack,
                         Button, HLine, Choice, Check, MenuItem, COLORS,
                         set_color, CEN, RIGHT, LEFT, FRAMESTYLE, Font,
                         FONTSIZE, FONTSIZE_FW, FileSave, FileOpen,
                         flatnotebook, Popup, FileCheckList,
                         EditableListBox, ExceptionPopup)

XYWcards = "XY Data File(*.xy)|*.xy|All files (*.*)|*.*"
PlotWindowChoices = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

X_SCALES = [u'q (\u212B\u207B\u00B9)', u'2\u03B8 (\u00B0)', u'd (\u212B)']
Y_SCALES = ['linear', 'log']

PLOT_OPTS = {'Raw Data': 'raw',
                'Raw Data + Background' : 'raw+bkg',
                'Background-subtracted Data': 'sub'}
PLOT_CHOICES = list(PLOT_OPTS.keys())

SCALE_METHODS = {'Max Raw Intensity': 'raw_max',
                 'Mean Raw Intensity': 'raw_mean',
                 'Max Background-Subtracted Intensity': 'sub_max',                 
                 'Mean Background-Subtracted Intensity': 'sub_mean',                 
                 'Max Background Intensity': 'bkg_max',
                 'Mean Background Intensity': 'bkg_mean'}

def smooth_bruckner(y, smooth_points, iterations):
    y_original = y
    N_data = y.size
    N = smooth_points
    N_float = float(N)
    y = np.empty(N_data + N + N)

    y[0:N].fill(y_original[0])
    y[N:N + N_data] = y_original[0:N_data]
    y[N + N_data:N_data + N + N].fill(y_original[-1])

    y_avg = np.average(y)
    y_min = np.min(y)

    y_c = y_avg + 2. * (y_avg - y_min)
    y[y > y_c] = y_c

    window_size = N_float*2+1

    for j in range(0, iterations):
        window_avg = np.average(y[0: 2*N + 1])
        for i in range(N, N_data - 1 - N - 1):
            if y[i]>window_avg:
                y_new = window_avg
                #updating central value in average (first bracket)
                #and shifting average by one index (second bracket)
                window_avg += ((window_avg-y[i]) + (y[i+N+1]-y[i - N]))/window_size
                y[i] = y_new
            else:
                #shifting average by one index
                window_avg += (y[i+N+1]-y[i - N])/window_size
    return y[N:N + N_data]

def extract_background(x, y, smooth_width=0.1, iterations=40, cheb_order=40):
    """DIOPTAS
    Performs a background subtraction using bruckner smoothing and a chebyshev polynomial.
    Standard parameters are found to be optimal for synchrotron XRD.
    :param x: x-data of pattern
    :param y: y-data of pattern
    :param smooth_width: width of the window in x-units used for bruckner smoothing
    :param iterations: number of iterations for the bruckner smoothing

    :param cheb_order: order of the fitted chebyshev polynomial
    :return: vector of extracted y background
    """
    smooth_points = int((float(smooth_width) / (x[1] - x[0])))
    print('bkg ', smooth_points, iterations,cheb_order)
    y_smooth = smooth_bruckner(y, abs(smooth_points), iterations)
    # get cheb input parameters
    x_cheb = 2. * (x - x[0]) / (x[-1] - x[0]) - 1.
    cheb_params = chebfit(x_cheb, y_smooth, cheb_order)
    return np.polynomial.chebyshev.chebval(x_cheb, cheb_params)        

def calc_bgr(dset, qwid=0.1, nsmooth=40, cheb_order=40):             
    return extract_background(dset.q, dset.I, smooth_width=qwid,
                              iterations=nsmooth, cheb_order=cheb_order)

class XRD1DBrowserFrame(wx.Frame):
    """browse 1D XRD patterns"""
    def __init__(self, parent=None, _larch=None, **kws):
        wx.Frame.__init__(self, None, -1, title='1D XRD Browser',
                          style=FRAMESTYLE, size=(600, 600), **kws)
        self.parent = parent
        self.larch = _larch
        self.current_label = None
        self.datasets = {}
        self.form = {}
        self.createMenus()
        self.build()

    def createMenus(self):
        fmenu = wx.Menu()
        MenuItem(self, fmenu, "Read XY File",
                 "Read XRD 1D data from XY FIle",
                 self.onReadXY)

        MenuItem(self, fmenu, "Save XY File",
                 "Save XRD 1D data to XY FIle",
                 self.onSaveXY)

        menubar = wx.MenuBar()
        menubar.Append(fmenu, "&File")
        self.SetMenuBar(menubar)

    def onReadXY(self, event=None):
        print('read xy ')
        deffile = 'some.xy'
        sfile = FileOpen(self, 'Read XY Data',
                         default_file=deffile,
                         wildcard=XYWcards)
        if sfile is not None:
            print(' would read ', sfile)

    def onSaveXY(self, event=None):
        print('save xy ')
        deffile = 'some.xy'
        # self.datagroup.filename.replace('.', '_') + 'peak.modl'
        sfile = FileSave(self, 'Save XY Data',
                         default_file=deffile)
        if sfile is not None:
            print(' would save ', sfile)

    def build(self):
        sizer = wx.GridBagSizer(3, 3)
        sizer.SetVGap(3)
        sizer.SetHGap(3)

        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        splitter.SetMinimumPaneSize(220)

        # left side: list of XRD 1D patterns
        lpanel = wx.Panel(splitter)
        lpanel.SetMinSize((275, 350))

        # rpanel = scrolled.ScrolledPanel(splitter)
        rpanel = wx.Panel(splitter)
        rpanel.SetMinSize((400, 350))
        rpanel.SetSize((750, 550))

        ltop = wx.Panel(lpanel)

        def Btn(msg, x, act):
            b = Button(ltop, msg, size=(x, 30),  action=act)
            b.SetFont(Font(FONTSIZE))
            return b

        sel_none = Btn('Select None', 130, self.onSelNone)
        sel_all  = Btn('Select All', 130, self.onSelAll)

        self.filelist = FileCheckList(lpanel, main=self,
                                      select_action=self.show_dataset,
                                      remove_action=self.remove_dataset)
        set_color(self.filelist, 'list_fg', bg='list_bg')

        tsizer = wx.BoxSizer(wx.HORIZONTAL)
        tsizer.Add(sel_all, 1, LEFT|wx.GROW, 1)
        tsizer.Add(sel_none, 1, LEFT|wx.GROW, 1)
        pack(ltop, tsizer)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(ltop, 0, LEFT|wx.GROW, 1)
        sizer.Add(self.filelist, 1, LEFT|wx.GROW|wx.ALL, 1)
        pack(lpanel, sizer)

        # right side: parameters controlling display
        panel = GridPanel(rpanel, ncols=6, nrows=10, pad=3, itemstyle=LEFT)
        panel.sizer.SetVGap(3)
        panel.sizer.SetHGap(3)

        self.font_fixedwidth = wx.Font(FONTSIZE_FW, wx.MODERN, wx.NORMAL, wx.BOLD)

        # title row
        self.wids = wids = {}
        title = SimpleText(panel, '1D XRD Data Display', font=Font(FONTSIZE+2),
                           colour=COLORS['title'], style=LEFT)

        self.last_plot_type = 'one'
        self.plotone = Button(panel, 'Plot Current ', size=(125, -1),
                              action=self.onPlotOne)
        self.plotsel = Button(panel, 'Plot Selected ', size=(125, -1),
                              action=self.onPlotSel)
        wids['plotone'] = Choice(panel, choices=PLOT_CHOICES, default=0,
                                 action=self.onPlotOne, size=(200, -1))
        wids['plotsel'] = Choice(panel, choices=PLOT_CHOICES, default=0,
                                 action=self.onPlotSel, size=(200, -1))
        wids['xscale'] = Choice(panel, choices=X_SCALES, default=0,
                                 action=self.onPlotEither, size=(100, -1))

        opts = dict(default=False, size=(200, -1), action=self.onPlotEither)
        wids['plot_win']  = Choice(panel, size=(100, -1), choices=PlotWindowChoices,
                                   action=self.onPlotEither)
        wids['plot_win'].SetStringSelection('1')

        wids['auto_scale'] = Check(panel, default=True, label='auto?',
                                   action=self.auto_scale)
        wids['scale_method'] = Choice(panel, choices=list(SCALE_METHODS.keys()),
                                      size=(250, -1), action=self.auto_scale, default=0)

        wids['scale'] = FloatCtrl(panel, value=1.0, size=(90, -1), precision=2,
                                  action=self.set_scale)
        wids['energy_ev'] = FloatCtrl(panel, value=PLANCK_HC, size=(90, -1),
                                      precision=1, action=self.set_energy, minval=0.1)
        wids['wavelength'] = FloatCtrl(panel, value=1.000,  size=(90, -1), precision=6,
                                       action=self.set_wavelength, minval=1.e-5)
        
        wids['bkg_qwid'] = FloatSpin(panel, value=0.1, size=(90, -1), digits=2,
                                     increment=0.01,
                                     min_val=0.001, max_val=5, action=self.on_bkg)
        wids['bkg_nsmooth'] = FloatSpin(panel, value=30, size=(90, -1), 
                                        digits=0, min_val=2, max_val=200, action=self.on_bkg)
        wids['bkg_porder'] = FloatSpin(panel, value=40, size=(90, -1), 
                                        digits=0, min_val=2, max_val=200, action=self.on_bkg)
        
        def slabel(txt):
            return wx.StaticText(panel, label=txt)
        
        panel.Add(title, style=LEFT, dcol=5)
        panel.Add(self.plotsel, newrow=True)
        panel.Add(wids['plotsel'], dcol=2)
        panel.Add(slabel('X scale: '), style=LEFT)
        panel.Add(wids['xscale'])

        panel.Add(self.plotone, newrow=True)
        panel.Add(wids['plotone'], dcol=2)
        panel.Add(slabel(' Plot Window: '))
        panel.Add(wids['plot_win'])
        
        panel.Add((5, 5))
        panel.Add(HLine(panel, size=(550, 3)), dcol=5, newrow=True)
        panel.Add((5, 5))


        panel.Add(slabel(' X-ray Energy (eV): '), style=LEFT, newrow=True)
        panel.Add(wids['energy_ev'], dcol=2)
        panel.Add(slabel(' Wavelength (\u212B): '), style=LEFT, newrow=False)
        panel.Add(wids['wavelength'])

        panel.Add(slabel(' Scaling Factor: '), style=LEFT, newrow=True)
        panel.Add(wids['scale'])
        panel.Add(wids['auto_scale'])
        panel.Add(slabel(' Scaling Method: '), style=LEFT, newrow=True)
        panel.Add(wids['scale_method'], dcol=3)

        panel.Add((5, 5))
        panel.Add(HLine(panel, size=(550, 3)), dcol=5, newrow=True)
        panel.Add((5, 5))

        panel.Add(slabel(' Background Subtraction Parameters: '), dcol=3, style=LEFT, newrow=True)
        panel.Add(slabel(' Q width (\u212B\u207B\u00B9): '), style=LEFT)
        panel.Add(wids['bkg_qwid'])        
        panel.Add(slabel(' Smoothing Steps: '), style=LEFT, newrow=True)
        panel.Add(wids['bkg_nsmooth'], dcol=2)
        panel.Add(slabel(' Polynomial Order: '), style=LEFT, newrow=False)
        panel.Add(wids['bkg_porder'])                
        panel.pack()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add((5, 5), 0, LEFT, 3)
        sizer.Add(panel, 0, LEFT, 3)
        sizer.Add((5, 5), 0, LEFT, 3)
        pack(rpanel, sizer)

        # rpanel.SetupScrolling()

        splitter.SplitVertically(lpanel, rpanel, 1)
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(splitter, 1, wx.GROW|wx.ALL, 5)
        pack(self, mainsizer)
        print(self, self.GetBestSize())
        self.SetSize( (850, 400))

        self.Show()
        self.Raise()

    def set_energy(self, event=None, value=None):
        if value is None:
            value = wids['energy_ev'].GetValue()
        if 'wavelength' in self.wids:
            self.wids['wavelength'].SetValue(PLANCK_HC/value, act=False)

    def set_wavelength(self, event=None, value=None):
        if value is None:        
            value = wids['wavelength'].GetValue()
        if 'energy_ev' in self.wids:
            print("Set E from Ang =", value)
            self.wids['energy_ev'].SetValue(PLANCK_HC/value, act=False)
        
    def onSelNone(self, event=None):
        self.filelist.select_none()

    def onSelAll(self, event=None):
        self.filelist.select_all()

    def on_bkg(self, event=None, value=None):
        try:
            qwid = self.wids['bkg_qwid'].GetValue()
            nsmooth = int(self.wids['bkg_nsmooth'].GetValue())
            cheb_order = int(self.wids['bkg_porder'].GetValue())
        except:
            return
        label = self.current_label
        if label not in self.datasets:
            return
        dset = self.datasets[label]
        dset.bkgd = calc_bgr(dset, qwid=qwid, nsmooth=nsmooth,
                             cheb_order=cheb_order)
        if 'back' not in self.wids['plotone'].GetStringSelection().lower():
            self.wids['plotone'].SetSelection(1)
        else:
            self.onPlotOne()
        
    def show_dataset(self, event=None, label=None):
        print('show xd1d ', event, label)
        if label is None and event is not None:
            label = str(event.GetString())
        if label not in self.datasets:
            print('dataset not found ', label)

        self.current_label = label
        dset = self.datasets[label]

        if not hasattr(dset, 'scale'):
            dset.scale = dset.I.max()
            dset.scale_method = 'raw_max'
            dset.auto_scale = True
        bkgd = getattr(dset, 'bkgd', None)
        if (bkgd is None
            or (isinstance(bkgd, np.ndarray)
                and (bkgd.sum() < 0.5/len(bkgd)))):
            dset.bkgd = calc_bgr(dset)

        print("INIT Background " , dset.bkgd)

        self.wids['scale'].SetValue(dset.scale)
        self.wids['auto_scale'].SetValue(dset.auto_scale)
        self.wids['energy_ev'].SetValue(dset.energy*1000.0)
        self.wids['scale_method'].SetSelection(0)
        self.onPlotOne(label=label)
        
    def set_scale(self, event=None, value=-1.0):
        label = self.current_label
        if label not in self.datasets:
            print('dataset not found ', label)
            return
        if value < 0:
            value = self.wids['scale'].GetValue()
        self.datasets[label].scale = value # self.wids['scale'].GetValue()

    def auto_scale(self, event=None):
        label = self.current_label
        if label not in self.datasets:
            print('dataset not found ', label)
            return
        dset = self.datasets[label]
        dset.auto_scale = self.wids['auto_scale'].IsChecked()
        self.wids['scale_method'].Enable(dset.auto_scale)
            
        if dset.auto_scale:
            meth_name = self.wids['scale_method'].GetStringSelection()

            meth = dset.scale_method = SCALE_METHODS[meth_name]
            if not meth.startswith('raw'):
                qwid = self.wids['bkg_qwid'].GetValue()
                nsmooth = int(self.wids['bkg_nsmooth'].GetValue())
                cheb_order = int(self.wids['bkg_porder'].GetValue())
                dset.bkgd = calc_bgr(dset, qwid=qwid,
                                     nsmooth=nsmooth,
                                     cheb_order=cheb_order)
            
            scale =  -1
            if meth == 'raw_max':
                scale = dset.I.max()
            elif meth == 'raw_mean':
                scale = dset.I.mean()                
            elif meth == 'sub_max':
                scale = (dset.I - dset.bkgd).max()                
            elif meth == 'sub_mean':
                scale = (dset.I - dset.bkgd).mean()
            elif meth == 'bkg_max':
                scale = (dset.bkgd).max()                
            elif meth == 'bkg_mean':
                scale = (dset.bkgd).mean()

            if scale > 0:
                self.wids['scale'].SetValue(scale)
                self.onPlotOne()

    def remove_dataset(self, event=None):
        print('remove dataset ', event.GetString())

    def get_display(self, win=1, stacked=False):
        wintitle='XRD Plot Window %i' % win
        opts = dict(wintitle=wintitle, stacked=stacked, win=win, linewidth=3)
        return self.larch.symtable._plotter.get_display(**opts)

    def onPlotOne(self, event=None, label=None):
        if label is None:
            label = self.current_label
        if label not in self.datasets:
            return
        dset = self.datasets[label]
        self.last_plot_type = 'one'
        win    = int(self.wids['plot_win'].GetStringSelection())
        xscale = self.wids['xscale'].GetSelection()
        xlabel = self.wids['xscale'].GetStringSelection()
        xdat = dset.q
        if xscale == 2:
           xdat = dset.d
        elif xscale == 1:
            xdat = dset.twth
        ytype = self.wids['plotone'].GetStringSelection().lower()

        ydat = 1.0*dset.I/dset.scale
        ylabel = 'Scaled Intensity'
        if ytype.startswith('background-sub'):
            ydat = 1.0*(dset.I-dset.bkgd)/dset.scale
            ylabel = 'Scaled (Intensity - Background)'

        pframe = self.get_display(win=win)
        pframe.plot(xdat, ydat, xlabel=xlabel, ylabel=ylabel,
                    label=dset.label, show_legend=True)
        if ytype.startswith('data') and 'background' in ytype:
            print("DATA SET bkg ", dset.bkgd, dset.bkgd.dtype)
            y2dat = 1.0*dset.bkgd/dset.scale
            ylabel = 'Scaled Intensity with Background'
            pframe.oplot(xdat, y2dat, xlabel=xlabel, ylabel=ylabel,
                         label='background', show_legend=True)

        wx.CallAfter(self.SetFocus)

    def onPlotSel(self, event=None):
        labels = self.filelist.GetCheckedStrings()
        if len(labels) < 1:
            return
        self.last_plot_type = 'multi'
        last_id = group_ids[-1]

    def onPlotEither(self, event=None):
        if self.last_plot_type == 'multi':
            self.onPlotSel(event=event)
        else:
            self.onPlotOne(event=event)


    def add_data(self, dataset, label=None,  **kws):
        print("add dataset ", dataset, label)
        if label is None:
            label = 'XRD pattern'
        self.filelist.Append(label)
        self.datasets[label] = dataset
        self.show_dataset(label=label)

