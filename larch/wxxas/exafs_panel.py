#!/usr/bin/env python
"""
Linear Combination panel
"""
import os
import time
import copy
import wx
import numpy as np

from functools import partial

from larch.math import index_of
from larch.wxlib import (BitmapButton, FloatCtrl, FloatSpin, ToggleButton,
                         get_icon, SimpleText, pack, Button, HLine, Choice,
                         plotlabels, Check, CEN, RIGHT, LEFT)

from larch.xafs.xafsutils import etok, ktoe


from .xas_dialogs import EnergyUnitsDialog
from .taskpanel import TaskPanel

np.seterr(all='ignore')

# plot options:
mu_bkg  = '\u03bC(E) + \u03bc0(E)'
chie    = '\u03c7(E)'
chik    = '\u03c7(k)'
chikwin = '\u03c7(k) + Window(k)'
chirmag = '|\u03c7(R)|'
chirre  = 'Re[\u03c7(R)]'
chirmr  = '|\u03c7(R)| + Re[\u03c7(R)]'
wavelet = 'EXAFS wavelet'
chir_w  = '\u03c7(R) + Window(R)'
chiq    = 'Filtered \u03c7(k)'
chikq   = '\u03c7(k) + Filtered \u03c7(k)'
noplot  = '<no plot>'

PlotOne_Choices = [mu_bkg, chie, chik, chikwin, chirmag, chirre, chirmr, wavelet,
                   chir_w, chiq, chikq]
PlotAlt_Choices = [noplot] + PlotOne_Choices
PlotSel_Choices = [chie, chik, chirmag, chirre]


PlotCmds = {mu_bkg:  "plot_bkg({group:s}",
            chie:    "plot_chie({group:s}",
            chik:    "plot_chik({group:s}, show_window=False, kweight={plot_kweight:.0f}",
            chikwin: "plot_chik({group:s}, show_window=True, kweight={plot_kweight:.0f}",
            chirmag: "plot_chir({group:s}, show_mag=True, show_real=False",
            chirre:  "plot_chir({group:s}, show_mag=False, show_real=True",
            chirmr:  "plot_chir({group:s}, show_mag=True, show_real=True",
            wavelet: "plot_wavelet({group:s}",
            chir_w:  "plot_chir({group:s}, show_mag=True, show_real=True, show_window=True",
            chiq:    "plot_chiq({group:s}, show_chik=False",
            chikq:   "plot_chiq({group:s}, show_chik=True",
            noplot: None}

FTWINDOWS = ('Kaiser-Bessel', 'Hanning', 'Gaussian', 'Sine', 'Parzen', 'Welch')

CLAMPLIST = ('0', '1', '2', '5', '10', '20', '50', '100', '200', '500', '1000',
             '2000', '5000', '10000')

autobk_cmd = """autobk({group:s}, rbkg={rbkg: .3f}, e0={e0: .4f},
      kmin={bkg_kmin: .3f}, kmax={bkg_kmax: .3f}, kweight={bkg_kweight: .1f},
      clamp_lo={bkg_clamplo: .1f}, clamp_hi={bkg_clamphi: .1f})"""

xftf_cmd = """xftf({group:s}, kmin={fft_kmin: .3f}, kmax={fft_kmax: .3f},
      kweight={fft_kweight: .3f}, dk={fft_dk: .3f}, window='{fft_kwindow:s}')"""

xftr_cmd = """xftr({group:s}, rmin={fft_rmin: .3f}, rmax={fft_rmax: .3f},
      dr={fft_dr: .3f}, window='{fft_rwindow:s}')"""


defaults = dict(e0=-1.0, rbkg=1, bkg_kmin=0, bkg_kmax=None, bkg_clamplo=0,
                bkg_clamphi=1, bkg_kweight=2, fft_kmin=2.5, fft_kmax=None,
                fft_dk=4, fft_kweight=2, fft_kwindow='Kaiser-Bessel',
                fft_rmin=1, fft_rmax=6, fft_dr=0.25,
                fft_rwindow='Hanning')


class EXAFSPanel(TaskPanel):
    """EXAFS Panel"""
    def __init__(self, parent, controller, **kws):
        TaskPanel.__init__(self, parent, controller,
                           configname='exafs_config',
                           title='EXAFS Background Subtraction and Fourier Transforms',
                           config=defaults, **kws)
        self.skip_process = False
        self.last_plot = 'one'
        self.last_process_bkg = {}
        self.last_process_fft = {}
        self.last_process_time = time.time() - 5000

    def build_display(self):
        panel = self.panel
        wids = self.wids
        self.skip_process = True

        wids['plotone_op'] = Choice(panel, choices=PlotOne_Choices,
                                    action=self.onPlotOne, size=(175, -1))
        wids['plotalt_op'] = Choice(panel, choices=PlotAlt_Choices,
                                    action=self.onPlotOne, size=(175, -1))
        wids['plotsel_op'] = Choice(panel, choices=PlotSel_Choices,
                                    action=self.onPlotSel, size=(175, -1))

        wids['plotone_op'].SetStringSelection(chik)
        wids['plotsel_op'].SetStringSelection(chik)
        wids['plotalt_op'].SetStringSelection(noplot)

        plot_one = Button(panel, 'Plot This Group', size=(175, -1),
                          action=self.onPlotOne)

        plot_sel = Button(panel, 'Plot Selected Groups', size=(175, -1),
                          action=self.onPlotSel)


        saveconf = Button(panel, 'Save as Default Settings', size=(200, -1),
                          action=self.onSaveConfigBtn)

        def xxxFSWithPinPanel(name, value, **kws):
            s = wx.BoxSizer(wx.HORIZONTAL)
            self.wids[name] = FloatSpin(panel, value=value, **kws)
            bb = BitmapButton(panel, get_icon('pin'), size=(25, 25),
                              action=partial(self.onSelPoint, opt=name),
                              tooltip='use last point selected from plot')
            s.Add(self.wids[name])
            s.Add(bb)
            return s

        wids['plot_voffset'] = FloatSpin(panel, value=0, digits=2, increment=0.25,
                                         action=self.onProcess)
        wids['plot_kweight'] = FloatSpin(panel, value=2, digits=1, increment=1,
                                         action=self.onProcess,
                                         min_val=0, max_val=5)
        wids['plot_kweight_alt'] = FloatSpin(panel, value=2, digits=1, increment=1,
                                             action=self.onProcess,
                                             min_val=0, max_val=5)

        opts = dict(digits=2, increment=0.1, min_val=0, action=self.onProcess)
        wids['e0'] = FloatSpin(panel, **opts)

        opts['max_val'] = 6
        opts['action'] = self.onRbkg
        wids['rbkg'] = FloatSpin(panel, value=1.0, **opts)

        opts['action'] = self.onProcess
        opts['max_val'] = 125
        bkg_kmin = self.add_floatspin('bkg_kmin', value=0, with_pin=True, **opts)
        bkg_kmax = self.add_floatspin('bkg_kmax', value=20, with_pin=True, **opts)
        fft_kmin = self.add_floatspin('fft_kmin', value=0, with_pin=True, **opts)
        fft_kmax = self.add_floatspin('fft_kmax', value=20, with_pin=True, **opts)

        wids['fft_dk'] = FloatSpin(panel, value=3,  **opts)

        opts.update({'increment': 0.1, 'digits': 2, 'max_val': 20})
        fft_rmin = self.add_floatspin('fft_rmin', value=1, with_pin=True, **opts)
        fft_rmax = self.add_floatspin('fft_rmax', value=6, with_pin=True, **opts)

        wids['fft_dr'] = FloatSpin(panel, value=0.5,  **opts)

        opts.update({'increment': 1, 'digits': 1, 'max_val': 5})
        wids['bkg_kweight'] = FloatSpin(panel, value=2, **opts)
        wids['fft_kweight'] = FloatSpin(panel, value=2, **opts)

        opts = dict(choices=CLAMPLIST, size=(80, -1), action=self.onProcess)
        wids['bkg_clamplo'] = Choice(panel, **opts)
        wids['bkg_clamphi'] = Choice(panel, **opts)

        wids['fft_kwindow'] = Choice(panel, choices=list(FTWINDOWS),
                                     action=self.onProcess, size=(125, -1))


        wids['fft_rwindow'] = Choice(panel, choices=list(FTWINDOWS),
                                     action=self.onProcess, size=(125, -1))
        wids['fft_rwindow'].SetStringSelection('Hanning')


        self.wids['is_frozen'] = Check(panel, default=False, label='Freeze Group',
                                       action=self.onFreezeGroup)

        def add_text(text, dcol=1, newrow=True):
            panel.Add(SimpleText(panel, text), dcol=dcol, newrow=newrow)

        def CopyBtn(name):
            return Button(panel, 'Copy', size=(60, -1),
                          action=partial(self.onCopyParam, name))


        panel.Add(SimpleText(panel, 'EXAFS Data Reduction and Fourier Transforms',
                             size=(350, -1),  **self.titleopts), style=LEFT, dcol=6)

        panel.Add(plot_sel, newrow=True)
        panel.Add(self.wids['plotsel_op'], dcol=2)

        add_text('Vertical offset: ', newrow=False)
        panel.Add(wids['plot_voffset'], dcol=2)

        panel.Add(plot_one, newrow=True)
        panel.Add(self.wids['plotone_op'], dcol=2)

        add_text('Plot k weight: ', newrow=False)
        panel.Add(wids['plot_kweight'])

        add_text('Add Second Plot: ', newrow=True)
        panel.Add(self.wids['plotalt_op'], dcol=2)
        add_text('Plot2 k weight: ', newrow=False)
        panel.Add(wids['plot_kweight_alt'])


        panel.Add(HLine(panel, size=(500, 3)), dcol=6, newrow=True)

        panel.Add(SimpleText(panel, ' Background subtraction', size=(200, -1),
                             **self.titleopts), dcol=2, style=LEFT, newrow=True)
        panel.Add(SimpleText(panel, 'Copy To Selected Groups:'),
                  style=RIGHT, dcol=3)


        add_text('E0: ')
        panel.Add(wids['e0'])
        panel.Add((10, 10), dcol=2)
        panel.Add(CopyBtn('e0'), style=RIGHT)

        add_text('R bkg: ')
        panel.Add(wids['rbkg'])
        panel.Add((10, 10), dcol=2)
        panel.Add(CopyBtn('rbkg'), style=RIGHT)

        add_text('k min: ')
        panel.Add(bkg_kmin)
        panel.Add(SimpleText(panel, 'k max:'), style=LEFT)
        panel.Add(bkg_kmax)
        panel.Add(CopyBtn('bkg_krange'), style=RIGHT)

        add_text('kweight: ', newrow=True)
        panel.Add(wids['bkg_kweight'])
        panel.Add((10, 10), dcol=2)
        panel.Add(CopyBtn('bkg_kweight'), style=RIGHT)

        add_text('Clamps Low E: ', newrow=True)
        panel.Add( wids['bkg_clamplo'])
        add_text('high E: ',  newrow=False)
        panel.Add( wids['bkg_clamphi'])
        panel.Add(CopyBtn('bkg_clamp'), style=RIGHT)

        panel.Add(HLine(panel, size=(500, 3)), dcol=6, newrow=True)

        panel.Add(SimpleText(panel, ' Fourier transform (k->R) ', size=(275, -1),
                             **self.titleopts), dcol=2, style=LEFT, newrow=True)
        panel.Add(SimpleText(panel, 'Copy To Selected Groups:'),
                  style=RIGHT, dcol=3)

        panel.Add(SimpleText(panel, 'k min: '), newrow=True)
        panel.Add(fft_kmin)
        panel.Add(SimpleText(panel, 'k max:'), style=LEFT)
        panel.Add(fft_kmax)
        panel.Add(CopyBtn('fft_krange'), style=RIGHT)

        panel.Add(SimpleText(panel, 'k weight : '), newrow=True)
        panel.Add(wids['fft_kweight'])
        panel.Add((10, 10), dcol=2)
        panel.Add(CopyBtn('fft_kweight'), style=RIGHT)

        panel.Add(SimpleText(panel, 'k window : '), newrow=True)
        panel.Add(wids['fft_kwindow'])
        panel.Add(SimpleText(panel, 'dk : '))
        panel.Add(wids['fft_dk'])
        panel.Add(CopyBtn('fft_kwindow'), style=RIGHT)


        panel.Add((10, 10), newrow=True)
        panel.Add(HLine(panel, size=(500, 3)), dcol=6, newrow=True)

        panel.Add(SimpleText(panel, ' Back Fourier transform (R->q) ', size=(275, -1),
                             **self.titleopts), dcol=2, style=LEFT, newrow=True)
        panel.Add(SimpleText(panel, 'Copy To Selected Groups:'),
                  style=RIGHT, dcol=3)

        panel.Add(SimpleText(panel, 'R min: '), newrow=True)
        panel.Add(fft_rmin)

        panel.Add(SimpleText(panel, 'R max:'), style=LEFT)
        panel.Add(fft_rmax)
        panel.Add(CopyBtn('fft_rrange'), style=RIGHT)

        panel.Add(SimpleText(panel, 'R window : '), newrow=True)
        panel.Add(wids['fft_rwindow'])
        panel.Add(SimpleText(panel, 'dR : '))
        panel.Add(wids['fft_dr'])
        panel.Add(CopyBtn('fft_rwindow'), style=RIGHT)


        panel.Add((10, 10), newrow=True)
        panel.Add(self.wids['is_frozen'], dcol=1, newrow=True)
        panel.Add(saveconf, dcol=4)
        panel.Add((10, 10), newrow=True)
        panel.Add(HLine(self, size=(500, 3)), dcol=8, newrow=True)

        panel.pack()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add((10, 10), 0, LEFT, 3)
        sizer.Add(panel, 1, LEFT, 3)
        pack(self, sizer)
        self.skip_process = False

    def get_config(self, dgroup=None):
        """get and set processing configuration for a group"""
        if dgroup is None:
            dgroup = self.controller.get_group()
        if dgroup is None:
            return self.get_defaultconfig()

        conf = getattr(dgroup, self.configname, None)
        if conf is None:
            # initial reading: start with default then take Athena Project values
            conf = self.get_defaultconfig()

            bkg_kmax = conf.get('bkg_kmax', None)
            fft_kmax = conf.get('fft_kmax', None)
            if None in (bkg_kmax, fft_kmax):
                e0 = conf.get('e0', -1)
                emin = min(dgroup.energy)
                if e0 is None or e0 < emin:
                    e0 = getattr(dgroup, 'e0',  emin)
                kmax = etok(max(dgroup.energy) - e0)

                if bkg_kmax is None or bkg_kmax < 0:
                    conf['bkg_kmax'] = kmax + 0.1
                if fft_kmax is None or fft_kmax < 0:
                    conf['fft_kmax'] = kmax - 1

            if hasattr(dgroup, 'bkg_params'): # from Athena
                conf['e0'] =  dgroup.bkg_params.e0
                conf['rbkg'] =  dgroup.bkg_params.rbkg
                conf['bkg_kmin'] =  dgroup.bkg_params.spl1
                conf['bkg_kmax'] =  dgroup.bkg_params.spl2
                conf['bkg_kweight'] =  dgroup.bkg_params.kw
                conf['bkg_clamplo'] =  dgroup.bkg_params.clamp1
                conf['bkg_clamphi'] =  dgroup.bkg_params.clamp2

            if hasattr(dgroup, 'fft_params'): # from Athena
                conf['fft_kmin'] =  2.0
                conf['fft_kmax'] =  None
                conf['fft_dk'] =  4.0
                conf['fft_kwindow'] =  'kaiser-bessel'
                conf['fft_kweight'] =  2
                if hasattr(dgroup.fft_params, 'kw'):
                    conf[f'fft_kweight'] = getattr(dgroup.fft_params, 'kw')
                for attr in ('kmin', 'kmax', 'dk', 'kwindow'):
                    if hasattr(dgroup.fft_params, attr):
                        conf[f'fft_{attr:s}'] = getattr(dgroup.fft_params, attr)

            setattr(dgroup, self.configname, conf)
        return conf

    def fill_form(self, dgroup):
        """fill in form from a data group"""
        opts = self.get_config(dgroup)
        self.dgroup = dgroup
        if not hasattr(dgroup, 'norm'):
            self.xasmain.process_normalization(dgroup)

        self.skip_process = True
        wids = self.wids
        for attr in ('e0', 'rbkg', 'bkg_kmin', 'bkg_kmax',
                     'bkg_kweight', 'fft_kmin', 'fft_kmax',
                     'fft_kweight', 'fft_dk'):
            val = getattr(dgroup, attr, None)
            if val is None:
                val = opts.get(attr, -1)
            wids[attr].SetValue(val)

        for attr in ('bkg_clamplo', 'bkg_clamphi'):
            val = getattr(dgroup, attr, None)
            if val is None:
                val = opts.get(attr, -1)
                if val is None:
                    val = '0'
            try:
                wids[attr].SetStringSelection("%d" % float(opts.get(attr, 0)))
            except:
                print(f"could not set '{attr:s}' to {val}")


        for attr in ('fft_kwindow', 'plotone_op', 'plotsel_op', 'plotalt_op'):
            if attr in opts:
                wids[attr].SetStringSelection(opts[attr])

        frozen = opts.get('is_frozen', False)
        if hasattr(dgroup, 'is_frozen'):
            frozen = dgroup.is_frozen

        self.wids['is_frozen'].SetValue(frozen)
        self._set_frozen(frozen)

        self.skip_process = False

    def read_form(self, dgroup=None, as_copy=False):
        "read form, return dict of values"
        skip_save = self.skip_process
        self.skip_process = True

        if dgroup is None:
            dgroup = self.controller.get_group()
        self.dgroup = dgroup

        conf = self.get_config()
        if dgroup is not None:
            conf['group'] = dgroup.groupname

        wids = self.wids
        for attr in ('e0', 'rbkg', 'bkg_kmin', 'bkg_kmax',
                     'bkg_kweight', 'fft_kmin', 'fft_kmax',
                     'fft_kweight', 'fft_dk',
                     'fft_rmin', 'fft_rmax', 'fft_dr',
                     'plot_kweight',
                     'plot_kweight_alt', 'plot_voffset'):
            conf[attr] = wids[attr].GetValue()

        for attr in ('bkg_clamplo', 'bkg_clamphi'):
            conf[attr] = int(wids[attr].GetStringSelection())

        for attr in ('fft_kwindow', 'fft_rwindow', 'plotone_op',
                     'plotsel_op', 'plotalt_op'):
            conf[attr] = wids[attr].GetStringSelection()
        time.sleep(0.001)
        self.skip_process = skip_save
        if as_copy:
            conf = copy.deepcopy(conf)
        if dgroup is not None:
            setattr(dgroup, self.configname, conf)
        return conf


    def onSaveConfigBtn(self, evt=None):
        self.set_defaultconfig(self.read_form())

    def onCopyParam(self, name=None, evt=None):
        conf = self.read_form()
        opts = {}
        def copy_attrs(*args):
            return {a: conf[a] for a in args}
        name = str(name)
        if name in ('e0', 'rbkg', 'bkg_kweight', 'fft_kweight'):
            opts = copy_attrs(name)
        elif name == 'bkg_krange':
            opts = copy_attrs('bkg_kmin', 'bkg_kmax')
        elif name == 'bkg_clamp':
            opts = copy_attrs('bkg_clamplo', 'bkg_clamphi')
        elif name == 'fft_krange':
            opts = copy_attrs('fft_kmin', 'fft_kmax')
        elif name == 'fft_kwindow':
            opts = copy_attrs('fft_kwindow', 'fft_dk')
        elif name == 'fft_rrange':
            opts = copy_attrs('fft_rmin', 'fft_rmax')
        elif name == 'fft_rwindow':
            opts = copy_attrs('fft_rwindow', 'fft_dr')

        for checked in self.controller.filelist.GetCheckedStrings():
            groupname = self.controller.file_groups[str(checked)]
            grp = self.controller.get_group(groupname)
            if grp != self.controller.group and not grp.is_frozen:
                self.update_config(opts, dgroup=grp)


    def _set_frozen(self, frozen):
        try:
            dgroup = self.controller.get_group()
            dgroup.is_frozen = frozen
        except:
            pass

        for attr in ('e0', 'rbkg', 'bkg_kmin', 'bkg_kmax', 'bkg_kweight',
                     'fft_kmin', 'fft_kmax', 'fft_kweight', 'fft_dk',
                     'fft_rmin', 'fft_rmax', 'fft_dr',
                     'bkg_clamplo', 'bkg_clamphi', 'fft_kwindow'):
            self.wids[attr].Enable(not frozen)

    def onFreezeGroup(self, evt=None):
        self._set_frozen(evt.IsChecked())


    def onRbkg(self, event=None):
        self.wids['fft_rmin'].SetValue(self.wids['rbkg'].GetValue())
        self.onProcess(event=event)

    def onProcess(self, event=None):
        """ handle process events"""
        if self.skip_process or ((time.time() - self.last_process_time) < 0.5):
            return
        self.last_process_time = time.time()
        self.skip_process = True
        self.process(dgroup=self.dgroup, read_form=True)
        self.skip_process = False
        plotter = self.onPlotSel if self.last_plot=='selected' else self.onPlotOne
        plotter()

    def process(self, dgroup=None, read_form=True, force=False, **kws):
        conf = {}
        if dgroup is not None:
            self.dgroup = dgroup
            conf = getattr(dgroup, self.configname, None)
            if conf is None:
                conf = self.get_config(dgroup=dgroup)

        if read_form:
            conf.update(self.read_form())

        conf.update(kws)
        if dgroup is None or 'fft_kwindow' not in conf:
            return

        # if 'group' not in conf:
        conf['group'] = dgroup.groupname

        try:
            txt = autobk_cmd.format(**conf)
        except:
            conf.update(self.read_form())

        bkgpars = []
        for attr in ('e0', 'rbkg', 'bkg_kmin', 'bkg_kmax',
                     'bkg_kweight', 'bkg_clamplo', 'bkg_clamphi'):
            val = conf.get(attr, 0.0)
            if val is None:
                val = -1.0
            bkgpars.append("%.3f" % val)
        bkgpars = ':'.join(bkgpars)
        lastpars = self.last_process_bkg.get(self.dgroup.groupname, '')
        if force or (bkgpars != lastpars):
            self.larch_eval(autobk_cmd.format(**conf))
            self.last_process_bkg[self.dgroup.groupname] = bkgpars
            self.last_process_fft[self.dgroup.groupname] = ''

        fftpars = [conf['fft_kwindow'], conf['fft_rwindow']]
        for attr in ('fft_kmin', 'fft_kmax', 'fft_kweight', 'fft_dk',
                     'fft_rmin', 'fft_rmax', 'fft_dr'):
            fftpars.append("%.3f" % conf.get(attr, 0.0))
        fftpars = ':'.join(fftpars)
        if fftpars != self.last_process_fft.get(self.dgroup.groupname, ''):
            self.larch_eval(xftf_cmd.format(**conf))
            self.larch_eval(xftr_cmd.format(**conf))
            self.last_process_fft[self.dgroup.groupname] = fftpars

        setattr(dgroup, self.configname, conf)

    def plot(self, dgroup=None):
        if self.skip_plotting:
            return
        self.onPlotOne(dgroup=dgroup)

    def onPlotOne(self, evt=None, dgroup=None):
        if self.skip_plotting:
            return
        conf = self.read_form(as_copy=True)
        if dgroup is not None:
            self.dgroup = dgroup
            conf['group'] = dgroup.groupname
        self.process(dgroup=self.dgroup)
        conf['title'] = '"%s"' % self.dgroup.filename

        cmd = PlotCmds[conf['plotone_op']] + ", win=1, title={title:s})"
        # 2nd plot
        cmd2 =  PlotCmds[conf['plotalt_op']]
        if cmd2 is not None:
            cmd2 = cmd2.replace('plot_kweight', 'plot_kweight_alt')
            cmd2 = cmd2 + ", win=2, title={title:s})"
            cmd = "%s\n%s" % (cmd, cmd2)
            self.controller.get_display(win=2)

        self.larch_eval(cmd.format(**conf))
        self.last_plot = 'one'
        self.parent.SetFocus()
        # if evt is not None:
        #     evt.Skip()

    def onPlotSel(self, evt=None):
        if self.skip_plotting:
            return
        group_ids = self.controller.filelist.GetCheckedStrings()
        if len(group_ids) < 1:
            return

        conf = self.read_form(as_copy=True)
        bcmd = PlotCmds[conf['plotsel_op']]
        conf['new'] = 'True'
        offset = conf['plot_voffset']
        for i, checked in enumerate(group_ids):
            groupname = self.controller.file_groups[str(checked)]
            dgroup = self.controller.get_group(groupname)
            if dgroup is not None:
                conf['group'] = dgroup.groupname
                conf['label'] = dgroup.filename
                conf['offset'] = offset * i
                if not hasattr(dgroup, 'chir_mag'):
                    self.process(dgroup=dgroup, read_form=False)

                extra = """, offset={offset:.3f}, win=1, delay_draw=True,
    label='{label:s}', new={new:s})"""
                cmd = "%s%s" % (bcmd, extra)
                self.larch_eval(cmd.format(**conf))
                conf['new'] = 'False'

        self.larch_eval("redraw(win=1, show_legend=True)")
        self.last_plot = 'selected'
        self.parent.SetFocus()
        # if evt is not None:
        #    evt.Skip()
