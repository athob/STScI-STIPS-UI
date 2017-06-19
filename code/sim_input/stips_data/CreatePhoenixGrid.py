import glob
import os
import time

os.environ["PYSYN_CDBS"] = os.path.join(os.getcwd(), "cdbs")
os.environ["pandeia_refdata"] = os.path.join(os.getcwd(), "pandeia_data")

import numpy as np
import pysynphot as ps
from pandeia.engine.instrument_factory import InstrumentFactory
from astropy.io import fits as pyfits

COMPFILES =  sorted(glob.glob(os.path.join(os.environ["PYSYN_CDBS"],"mtab","*tmc.fits")))
GRAPHFILES = sorted(glob.glob(os.path.join(os.environ["PYSYN_CDBS"],"mtab","*tmg.fits")))
THERMFILES = sorted(glob.glob(os.path.join(os.environ["PYSYN_CDBS"],"mtab","*tmt.fits")))
wfc3_refs = {   
                'comptable': COMPFILES[-2],
                'graphtable': GRAPHFILES[-2],
                'thermtable': THERMFILES[-2],
                'area': 45238.93416,
                'waveset': (500,26000,10000.,'log')
            }

instruments = ['nircam', 'miri', 'wfirstimager', 'wfc3']
area =  {
            'nircam':       253260.0,
            'miri':         253260.0,
            'wfc3':         45238.93416,
            'wfirstimager': 45238.93416
        }
modes = {   'nircam':       ['sw_imaging', 'lw_imaging'],
            'miri':         ['imaging'],
            'wfc3':         ['imaging'],
            'wfirstimager': ['imaging']
        }
filters = {
            'nircam':   {
                            'sw_imaging':   [ 
                                                "f070w", "f090w", "f115w", "f140m", "f150w", "f162m",
                                                "f164n", "f182m", "f187n", "f200w", "f210m", "f212n",
                                                "f225n"
                                            ],
                            'lw_imaging':   [
                                                "f250m", "f277w", "f300m", "f322w", "f323n", "f335m",
                                                "f356w", "f360m", "f405n", "f410m", "f418n", "f430m",
                                                "f444w", "f460m", "f466n", "f470n", "f480m"
                                            ]
                        },
            'miri':     {
                            'imaging': [
                                            "f560w", "f770w", "f1000w", "f1130w", "f1280w", "f1500w", 
                                            "f1800w", "f2100w", "f2550w"
                                        ]
                        },
            'wfc3':     {
                            'imaging': [
                                            "f105w", "f110w", "f125w", "f126n", "f127m", "f128n", 
                                            "f130n", "f132n", "f139m", "f140w", "f153m", "f160w", 
                                            "f164n", "f167n"
                                        ]
                        },
            'wfirstimager': {
                                'imaging':  [
                                                'z087', 'y106', 'w149', 'j129', 'h158', 'f184'
                                            ]
                            }
          }
apertures = {
                'nircam':   {
                                'sw_imaging':   "sw",
                                'lw_imaging':   "lw"
                        },
                'miri':     {
                                'imaging':      "imager"
                            },
                'wfc3':     {
                                'imaging':      "default"
                            },
                'wfirstimager': {
                                    'imaging':  "any"
                                }
            }

def get_pce(instrument, mode, filter, aperture, disperser):

    obsmode = {
               'instrument': instrument,
               'mode': mode,
               'filter': filter,
               'aperture': aperture,
               'disperser': disperser
               }

    conf = {'instrument': obsmode}

    i = InstrumentFactory(config=conf)
    wr = i.get_wave_range()
    wave = np.linspace(wr['wmin'], wr['wmax'], num=500)
    pce = i.get_total_eff(wave)
    
    return wave,pce

def get_grid_points():
    grid_file = os.path.join(os.getcwd(), "cdbs", "grid", "phoenix", "catalog.fits")
    teff, Z, logg = np.array(()), np.array(()), np.array(())
    with pyfits.open(grid_file) as inf:
        indices = inf[1].data.field('INDEX')
        for row in indices:
            items = row.split(",")
            teff = np.append(teff, float(items[0]))
            Z = np.append(Z, float(items[1]))
            logg = np.append(logg, float(items[2]))
    return np.array((np.unique(Z), np.unique(logg), np.unique(teff), np.arange(-5.5, 16.0)))

norm_bandpass = ps.ObsBandpass('johnson,i')
coords = get_grid_points()
print coords
bandpasses = {}
result_arrays = {}

print "{}: Making Bandpasses...".format(time.ctime())
for instrument in instruments:
    bandpasses[instrument] = {}
    result_arrays[instrument] = {}
    for mode in modes[instrument]:
        for filter in filters[instrument][mode]:
            print "\t{}: {},{},{},{}".format(time.ctime(), instrument, mode, filter, apertures[instrument][mode])
            if instrument == "wfc3":
                obsmode = "wfc3,ir,{}".format(filter)
                ps.setref(**wfc3_refs)
                bandpasses[instrument][filter] = ps.ObsBandpass(obsmode)
            else:
                wave, pce = get_pce(instrument, mode, filter, apertures[instrument][mode], None)
                bandpasses[instrument][filter] = ps.ArrayBandpass(wave=wave*1.e4, throughput=pce,
                                                                  waveunits='angstroms',
                                                                  name="bp_{}_{}".format(instrument, filter))
            result_arrays[instrument][filter] = np.empty((len(coords[0]), len(coords[1]), len(coords[2]), len(coords[3])))
print "Done\n"

n = 0
for i, Z in enumerate(coords[0]):
    print "{}: Starting Z = {}".format(time.ctime(), Z)
    for j, logg in enumerate(coords[1]):
        print "\t{}: Starting log(g) = {}".format(time.ctime(), logg)
        for k, teff in enumerate(coords[2]):
            print "\t\t{}: Starting Teff = {}".format(time.ctime(), teff)
            spec = ps.Icat('phoenix', teff, Z, logg)
            counts = False
            if sum(spec.flux) > 0:
                counts = True
            for l, mag in enumerate(coords[3]):
                print "\t\t\t{}: Starting Z = {}, log(g) = {}, Teff = {}, Mabs = {:>4}".format(time.ctime(), Z, logg, teff, mag),
                if counts:
                    spec_norm = spec.renorm(mag, 'vegamag', norm_bandpass)
                for instrument in instruments:
                    ps.setref(area=area[instrument], waveset=(500, 260000, 10000., 'log'))
                    for mode in modes[instrument]:
                        for filter in filters[instrument][mode]:
                            if counts:
                                obs = ps.Observation(spec_norm, bandpasses[instrument][filter], binset=spec_norm.wave)
                                result_arrays[instrument][filter][i,j,k,l] = obs.countrate()
                                print ".",
                            else:
                                result_arrays[instrument][filter][i,j,k,l] = 0.
                                print "x",
                print ""
                n += 1

print "{}: Saving files...".format(time.ctime()),
np.save(os.path.join(os.getcwd(), 'grid', 'input.npy'), coords)
for instrument in instruments:
    for mode in modes[instrument]:
        for filter in filters[instrument][mode]:
            addition = ''
            if instrument == "wfc3":
                addition = 'ir'
            np.save(os.path.join(os.getcwd(), 'grid', 'result_{}{}_{}.npy'.format(instrument, addition, filter)),
                    result_arrays[instrument][filter])
print "done"
