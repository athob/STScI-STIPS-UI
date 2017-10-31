#!/usr/bin/env python
from __future__ import absolute_import

# Set plot backend. Must happen before importing pylab.
import matplotlib
matplotlib.use('Agg')

from werkzeug import secure_filename
import cPickle, datetime, git, glob, json, logging, logging.config, os, platform, re, shutil, sys, numpy, sqlite3, time, zipfile
import montage_wrapper as montage
import unicodedata

from redis import ConnectionError
from flask import Flask, flash, g, jsonify, make_response, redirect, render_template, request, session, url_for
import flask_sijax
from sijax.plugin.upload import register_upload_callback
from celery import Celery, chain
from celery.utils import uuid
from celery.utils.log import get_task_logger
from argparse import ArgumentParser
from logging import FileHandler, Formatter, DEBUG
from astropy.io import fits as pyfits
from wtforms import HiddenField

os.environ['TERM'] = 'xterm'
os.environ['PYSYN_CDBS'] = os.path.join(os.getcwd(),'sim_input','cdbs')
os.environ['WEBBPSF_PATH'] = os.path.join(os.getcwd(),"sim_input","webbpsf-data")
os.environ['WEBBPSF_SKIP_CHECK'] = '1'
os.environ['pandeia_refdata'] = os.path.join(os.getcwd(), "sim_input", "pandeia_data")
os.environ['stips_data'] = os.path.join(os.getcwd(), "sim_input", "stips_data")

sys.path.append(os.path.join(os.getcwd(),"lib"))

repo_dir = os.getcwd()
if not os.path.exists(os.path.join(repo_dir, ".git")):
    repo_dir = os.path.abspath(os.path.join(repo_dir, ".."))
repo = git.Repo(repo_dir)
tree = repo.tree()
committed_date = 0
for blob in tree:
    commit = repo.iter_commits(paths=blob.path, max_count=1).next()
    if commit.committed_date > committed_date:
        committed_date = commit.committed_date
server_mod_time = datetime.datetime.fromtimestamp(committed_date)
print("Server Mod Time: {}".format(server_mod_time))

import imp
try:
    imp.find_module('stips')
    found = True
except ImportError:
    found = False

if not found:
    sys.path.append(os.path.join(os.getcwd(), "stips"))

import DefaultSettings

from Forms import *
from Templates import *
from Utilities import *

import stips
from stips.utilities import InstrumentList
from stips.scene_module import SceneModule
from stips.observation_module import ObservationModule

stips_version = stips.__version__

try:
    repo = git.Repo(os.path.split(os.path.split(stips.__file__)[0])[0])
except git.exc.InvalidGitRepositoryError as e:
    repo = git.Repo(os.path.split(os.path.split(os.path.split(stips.__file__)[0])[0])[0])
tree = repo.tree()
committed_date = 0
for blob in tree:
    commit = repo.iter_commits(paths=blob.path, max_count=1).next()
    if commit.committed_date > committed_date:
        committed_date = commit.committed_date
stips_mod_time = datetime.datetime.fromtimestamp(committed_date)
print("STIPS Mod Time: {}".format(stips_mod_time))
print("STIPS Version: {}".format(stips_version))

with open(os.path.join(os.environ['stips_data'], 'grid', 'VERSION.txt'), 'r') as inf:
    grid_pandeia_info = inf.readline().strip()
    grid_stips_info = inf.readline().strip()
print("Grid: {}, {}".format(grid_pandeia_info, grid_stips_info))

pandeia_version_file = os.path.join(os.environ["pandeia_refdata"], "VERSION_PSF")
with open(pandeia_version_file, 'r') as inf:
    pandeia_version_info = inf.readline().strip()
print("Pandeia Version: {}".format(pandeia_version_info))

app = Flask(__name__)
app.config['DEBUG'] = __name__ == '__main__'
app.config['PROPAGATE_EXCEPTIONS'] = True
app.config.from_object("DefaultSettings")
app.config['SIJAX_STATIC_PATH'] = os.path.join('.', os.path.dirname(__file__), app.config['_SIJ_PATH'])
app.config['SIJAX_JSON_URI'] = '/' + app.config['_SIJ_PATH']
flask_sijax.Sijax(app)
if os.path.exists('proxy.config'):
    f = open('proxy.config','rt')
    lines = f.readlines()
    for line in lines:
        line = line.strip()
        if line != "" and line[0] != "#":
            items = line.split()
            if "," in items[1]:
                app.config[items[0]] = items[1].split(",")
            else:
                app.config[items[0]] = items[1]
    f.close()
if "JWST_SIM_CONFIG" in os.environ:
    app.config.from_envvar('JWST_SIM_CONFIG')

celery_logger = get_task_logger(__name__)
celery_file_handler = FileHandler(os.path.join(os.getcwd(),"simulator.celery.log"))
celery_file_handler.setLevel(DEBUG)
celery_logger.addHandler(celery_file_handler)
celery_file_handler.setFormatter(Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))

def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'], backend=app.config['CELERY_RESULT_BACKEND'])
    celery.conf.update(app.config)
    celery.conf.update(app.config['CELERY_UPDATER'])
    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery

celery = make_celery(app)

if 'excludes' in app.config and isinstance(app.config['excludes'], str):
    app.config['excludes'] = app.config['excludes'].split(",")
elif 'excludes' not in app.config:
    app.config['excludes'] = []

instruments = InstrumentList(app.config['excludes'])
INSTRUMENTS = instruments.keys()
INSTRUMENTS.sort()

DefaultSettings.instruments = instruments
DefaultSettings.INSTRUMENTS = INSTRUMENTS

app.config['telescope'] = app.config.get('telescope', 'JWST-WFIRST')
telescope = app.config['telescope']
instrument_intro = instrument_intro_template[app.config['telescope']]

app.config['internal_only'] = app.config.get('internal_only', "0")
app.config['check_group'] = app.config.get('check_group', "0")
app.config['allowed_groups'] = app.config.get('allowed_groups', [])
app.config['check_users'] = app.config.get('check_users', "0")
app.config['user_db'] = app.config.get('user_db', None)
app.config['email_test'] = SendEmail('york@stsci.edu', 'Starting Simulator on {}'.format(platform.uname()[1]), 'Starting Simulator.\n', [])

@celery.task(bind=True,ignore_results=False,name="tasks.start_sequence")
def start_sequence(self,params):
    celery_logger.info("Params: {}".format(params))
    self.update_state(state="STARTING OBSERVATION SEQUENCE")
    params['start_time'] = datetime.datetime.now()
    out_prefix = params['out_prefix']
    task_files = glob.glob(os.path.join(params['out_path'],params['out_prefix']+'*'))
    found = False
    task_file = ""
    for f in task_files:
        if "initial" not in f:
            found = True
            task_file = os.path.splitext(os.path.split(f)[1])[0]
    if found and params['user']['email'] is not None:
        send_to = params['user']['email']
        subject = "Your STIPS simulation {} has started".format(out_prefix)
        send_text = start_email.substitute(progress_page=params['progress_page'], task_file=task_file)
        result = SendEmail(send_to, subject, send_text, [])
        if result != "":
            if 'errors' not in params:
                params['errors'] = []
            params['errors'].append(result)
    return params

@celery.task(bind=True,ignore_result=False,name="tasks.create_catalogues")
def create_catalogues(self,params):
    self.update_state(state="CREATE CATALOGUE STARTED")
    out_prefix = params['out_prefix']
    celery_logger.info("Creating catalogues for %s",out_prefix)
    sparams = params.copy()
    sparams['logger'] = celery_logger
    sparams['celery'] = self
    sce = SceneModule(**sparams)
    celery_logger.info("Created Scene Module for %s",out_prefix)
    catalogues = []
    for cat in params['in_cats']:
        catalogues.append(os.path.join(cat['file_path'], cat['current_filename']))
    celery_logger.info("Creating stars for %s",out_prefix)
    for i,pop in enumerate(params['stellar']):
        self.update_state(state="CREATE CATALOGUE CREATING STELLAR POPULATION %d OF %d"%(i+1,len(params['stellar'])))
        celery_logger.info("Creating Population %d for %s",i+1,out_prefix)
        catalogues.append(sce.CreatePopulation(pop,i))
    for i,gal in enumerate(params['galaxy']):
        self.update_state(state="CREATE CATALOGUE CREATING GALAXY POPULATION %d OF %d"%(i+1,len(params['galaxy'])))
        celery_logger.info("Creating Galaxies %d for %s",i+1,out_prefix)
        catalogues.append(sce.CreateGalaxies(gal,i))
    params['catalogues'] = catalogues
    params['observations_out'] = []
    return params

@celery.task(bind=True,ignore_result=False,name="tasks.observation")
def observation(self,params,observation):
    self.update_state(state="OBSERVATION STARTED")
    task_id = self.request.id
    def get_task_state():
        result = celery.AsyncResult(id=task_id)
        return result.state
    def set_task_state(state):
        self.update_state(state=state)
    out_prefix = params['out_prefix']
    sparams = params.copy()
    sparams['logger'] = celery_logger
    sparams['get_celery'] = get_task_state
    sparams['set_celery'] = set_task_state
    obs_num = int(observation['observations_id'])
    celery_logger.info("Running observation {} for simulation {}".format(obs_num, out_prefix))
    celery_logger.info("Observation Offsets are {}".format(observation['offsets']))
    obset = []
    obs = ObservationModule(observation,**sparams)
    n_obs = obs.totalObservations()
    for img in params['in_imgs']:
        obs.prepImage(img)
    current_obs = obs.nextObservation()
    while current_obs is not None:
        observed_catalogues = []
        obs_out = {}
        for i,img in enumerate(params['in_imgs']):
            self.update_state(state="OBSERVATION %d (PART %d of %d) ADDING BACKGROUND %d OF %d" % (obs_num,current_obs+1,n_obs,i+1,len(params['in_imgs'])))
            obs.addImage(img['current_filename'],img['units'])
        for i,cat in enumerate(params['catalogues']):
            (catpath,catname) = os.path.split(cat)
            self.update_state(state="OBSERVATION_%d_(PART_%d_of_%d)_OBSERVING_CATALOGUE_%s_(%d_OF_%d)" % (obs_num,current_obs+1,n_obs,catname,i+1,len(params['catalogues'])))
            celery_logger.info("Imaging Catalogue %s for %s",catname,out_prefix)
            observed_catalogues.extend(obs.addCatalogue(cat))
        self.update_state(state="OBSERVATION %d (PART %d of %d) ADDING ERROR" % (obs_num,current_obs+1,n_obs))
        psf_fits = obs.addError()
        out_fits,mosaic_fits,parsed_params = obs.finalize()
        celery_logger.info("Generating Quicklook Images for %s",out_fits)
        Fits2Png(out_fits,out_fits.replace(".fits",".png"),pngTitle=out_prefix + ' Quicklook',cbarLabel='electrons',scale='log')
        for mosaic in mosaic_fits:
            Fits2Png(mosaic,mosaic.replace(".fits",".png"),pngTitle=out_prefix + ' Quicklook',cbarLabel='electrons',scale='log')
        Fits2Png(psf_fits,psf_fits.replace(".fits",".png"),pngTitle=out_prefix+' PSF Quicklook')
        celery_logger.info('Generated Quicklook Images for %s',out_fits)
        obs_out['id'] = current_obs
        obs_out['out_fits'] = out_fits
        obs_out['mosaic_fits'] = mosaic_fits
        obs_out['psf_fits'] = psf_fits
        obs_out['observed_catalogues'] = observed_catalogues
        obs_out['parsedParam'] = parsed_params
        obs_out['filter'] = obs.instrument.filter
        obset.append(obs_out)
        current_obs = obs.nextObservation()
    params['observations_out'].append({'observations': obset, 'mosaics': [], 'pngs': []})
    return params

@celery.task(bind=True,ignore_result=False,name="tasks.finalize")
def finalize(self,params):
    self.update_state(state="FINALIZE")
    celery_logger.warning("Params: %s",params)
    catalogues = params['catalogues']
    current_dir = os.getcwd()
    #if more than one observation, make an overall mosaic
    params['overall_mosaics'] = []
    params['overall_pngs'] = []
    for i, obset in enumerate(params['observations_out']):
        if len(obset) > 1:
            self.update_state(state="FINALIZE MAKING MOSAIC OBS {} OF {}".format(i+1, len(params['observations_out'])))
            celery_logger.info("Making Full output mosaic for observation {}".format(i+1))
            out_obs = {}
            for obs in obset['observations']:
                if obs['filter'] in out_obs:
                    out_obs[obs['filter']].append(obs)
                else:
                    out_obs[obs['filter']] = [obs]
            for filter in out_obs.keys():
                if len(out_obs[filter]) > 1:
                    tmp_dir = os.path.join(params['out_path'],params['out_prefix']+"_"+str(uuid()))
                    os.makedirs(tmp_dir)
                    tmp_out_dir = os.path.join(params['out_path'],params['out_prefix']+"_out_"+str(uuid()))
                    tmp_work_dir = os.path.join(params['out_path'],params['out_prefix']+"_work_"+str(uuid()))
                    for obs in out_obs[filter]:
                        shutil.copy(obs['out_fits'],os.path.join(tmp_dir,os.path.split(obs['out_fits'])[1]))
                    montage.mosaic(tmp_dir,tmp_out_dir,background_match=True,work_dir=tmp_work_dir)
                    celery_logger.info("Mosaic for observation {} filter {} finished running".format(i+1, filter))
                    shutil.copy(os.path.join(tmp_out_dir,"mosaic.fits"),
                                os.path.join(params['out_path'],params['out_prefix']+"_{}_{}_overall_mosaic.fits".format(i+1, filter)))
                    if os.path.exists(tmp_dir):
                        shutil.rmtree(tmp_dir)
                    if os.path.exists(tmp_out_dir):
                        shutil.rmtree(tmp_out_dir)
                    if os.path.exists(tmp_work_dir):
                        shutil.rmtree(tmp_work_dir)
                    obset['mosaics'].append(os.path.join(params['out_path'], 
                                            params['out_prefix']+"_{}_{}_overall_mosaic.fits".format(i+1, filter)))
            obset['pngs'] = [fname.replace(".fits",".png") for fname in obset['mosaics']]
            for i in range(len(obset['mosaics'])):
                fname = os.path.split(obset['mosaics'][i])[1]
                fname_items = fname.split("_")
                filter = fname_items[2]
                Fits2Png(obset['mosaics'][i], obset['pngs'][i],
                         pngTitle=params['out_prefix']+' %s Quicklook'%(filter),cbarLabel='electrons',scale='log')
    self.update_state(state="FINALIZE MAKING ZIP FILE")
    os.chdir(params['out_path'])
    infiles = []
    with zipfile.ZipFile(params['out_prefix']+'.zip','w',allowZip64=True) as myzip:
        for cat in params['catalogues']:
            catname = os.path.split(cat)[1]
            if catname not in infiles:
                myzip.write(catname)
                infiles.append(catname)
        for obset in params['observations_out']:
            for obs in obset['observations']:
                fitsname = os.path.split(obs['out_fits'])[1]
                if fitsname not in infiles:
                    myzip.write(fitsname)
                    infiles.append(fitsname)
                for mosaic in obs['mosaic_fits']:
                    mosaicname = os.path.split(mosaic)[1]
                    if mosaicname not in infiles:
                        myzip.write(mosaicname)
                        infiles.append(mosaicname)
                psfname = os.path.split(obs['psf_fits'])[1]
                if psfname not in infiles:
                    myzip.write(psfname)
                    infiles.append(psfname)
                for cat in obs['observed_catalogues']:
                    catname = os.path.split(cat)[1]
                    if catname not in infiles:
                        myzip.write(catname)
                        infiles.append(catname)
            for mosaic in obset['mosaics']:
                mosaicname = os.path.split(mosaic)[1]
                if mosaicname not in infiles:
                    myzip.write(mosaicname)
                    infiles.append(mosaicname)
    os.chdir(current_dir)
    if params['user']['email'] is not None:
        self.update_state(state="FINALIZE CREATING FINISHED EMAIL")
        subject = "Your STIPS simulation {} has completed".format(params['out_prefix'])
        msg_to = params['user']['email']
        catalogue_names = [os.path.split(c)[1] for c in params['catalogues']]
        input_cats = "\n".join(["\t{} <{}{}>".format(cn, params['static_page'], cn) for cn in catalogue_names])
        obs_array = []
        out_files = []
        input_mosaics = []
        for obset in params['observations_out']:
            for obs in obset['observations']:
                cats = [os.path.split(c)[1] for c in obs['observed_catalogues']]
                cat_names = "\n".join(["\t\t{} <{}{}>\n".format(cn, params['static_page'], cn) for cn in cats])
                obs_array.append(observation_done_template.substitute(id=obs['id'], static=params['static_page'], fits=obs['out_fits'],
                                                                      cats=cat_names))
                out_files += [o.replace('.fits', '.png') for o in obs['mosaic_fits']] 
                out_files.append(obs['psf_fits'].replace('.fits', '.png'))
            for mosaic in obset['mosaics']:
                mosaic_name = os.path.split(mosaic)[1]
                filter = mosaic_name.split("_")[2]
                input_mosaics.append("\t{} Mosaic: <{}{}>".format(filter, params['static_page'], mosaic_name))
            for png in obset['pngs']:
                out_files.append(png)
        obs_str = "\n".join(obs_array)
        msg_text = done_email.substitute(final_page=params['final_page'], zip=params['static_page']+params['out_prefix']+'.zip',
                                         inputs=input_cats, mosaics=input_mosaics, observations=obs_str)
        result = SendEmail(msg_to, subject, msg_text, out_files)
        if result != "":
            if 'errors' not in params:
                params['errors'] = []
            params['errors'].append(result)
    self.update_state(state='FINISHED OBSERVATIONS')
    params['stop_time'] = datetime.datetime.now()
    f = open(os.path.join(params['out_path'],params['out_prefix']+'_final.pickle'),'wb')
    cPickle.dump(params,f)
    f.close()
    return params

@app.route('/',methods=['GET','POST'])
@app.route('/<raw_sim>',methods=['GET','POST'])
def input(raw_sim=None):
    sim = raw_sim
    if isinstance(raw_sim, str):
        sim = asciify(raw_sim[:1000])
#     print "All headers:"
#     print request.headers
    print "Internal Users Only: {}, user is internal: {}".format(app.config['internal_only'], request.headers.get('stsci-internal'))
    print "Check for Group ID: {}".format(app.config['check_group'])
    print "Allowed Groups: {}".format(app.config['allowed_groups'])
    for group in app.config['allowed_groups']:
        print "Group {} in headers: {}. Value: {}".format(group, group in request.headers, request.headers.get(group))
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    form_init_js = g.sijax.register_upload_callback('add_form', handle_form_upload)
    print("Sijax Request Received: {}".format(g.sijax.is_sijax_request))
    if g.sijax.is_sijax_request:
        return g.sijax.process_request()
    if sim is not None:
        user_email = asciify(request.cookies.get('user_email', u'')[:1000])
        app.logger.info("User E-mail Cookie has value: {}".format(user_email))
        inf = os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle")
        if not os.path.exists(inf):
            app.logger.error("Error: Simulation %s not found",sim)
            session['message'] = 'Simulation not found'
            session['description'] = 'Simulation %s not found' % (sim)
            flash("Simulation %s Not Found" % (sim))
            return redirect(url_for('error', raw_sim=sim))
        with open(inf, 'rb') as f:
            params = cPickle.load(f)
        app.logger.info("User E-mail loaded as '{}'".format(params['user']['email']))
        if params['user']['email'] == '' or params['user']['email'] is None:
            params['user']['email'] = user_email
            app.logger.info("User E-mail set to '{}'".format(params['user']['email']))
    else:
        uid = RandomPrefix()
        form = ParameterForm()
        params = form.data
        params['uid'] = uid
        params['active_form'] = False
        print("User E-mail initialized to '{}'".format(params['user']['email']))
        app.logger.info("User E-mail initialized to '{}'".format(params['user']['email']))
        with open(os.path.join(os.getcwd(), app.config['_CACHE_PATH'], uid+"_scm.pickle"), "wb") as outf:
            cPickle.dump(params, outf)
        print("Initial simulation parameters created")
        return redirect(url_for('input', raw_sim=uid))
    resp = make_response(render_template('input.html', params=params, instruments=INSTRUMENTS,
                                         telescope=telescope, instrument_intro=instrument_intro, 
                                         server_mod_time=server_mod_time, stips_version=stips_version, 
                                         stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, 
                                         grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info,
                                         email_test=app.config['email_test']))
    if params['user']['update_user'] == 'yes':
        if params['user']['save_user']:
            app.logger.info("Setting USER ID cookie to {}".format(params['user']['email']))
            resp.set_cookie('user_email', params['user']['email'])
        else:
            app.logger.info("Deleting USER ID cookie")
            resp.set_cookie('user_email', '', expires=0)
    return resp

@app.route('/repeat/<raw_sim>')
def repeat(raw_sim):
    sim = asciify(raw_sim[:1000])
    uid = RandomPrefix()
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    cache_file = os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle")
    if not os.path.exists(cache_file):
        print("CACHE FILE NOT FOUND!!!!!")
        app.logger.error("Error: Simulation %s not found",sim)
        session['message'] = 'Simulation not found'
        session['description'] = 'Simulation %s not found' % (sim)
        return redirect(url_for('error', raw_sim=sim))
    with open(cache_file, 'rb') as f:
        params = cPickle.load(f)
        params['uid'] = uid
        params['active_form'] = False
        with open(os.path.join(os.getcwd(), app.config['_CACHE_PATH'], uid+"_scm.pickle"), "wb") as outf:
            cPickle.dump(params, outf)
    return redirect(url_for('output', raw_sim=uid))        

@app.route('/edit/<raw_sim>')
def edit(raw_sim):
    sim = asciify(raw_sim[:1000])
    uid = RandomPrefix()
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    cache_file = os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle")
    if not os.path.exists(cache_file):
        print("CACHE FILE NOT FOUND!!!!!")
        app.logger.error("Error: Simulation %s not found",sim)
        session['message'] = 'Simulation not found'
        session['description'] = 'Simulation %s not found' % (sim)
        return redirect(url_for('error', raw_sim=sim))
    with open(cache_file, 'rb') as f:
        params = cPickle.load(f)
        params['uid'] = uid
        params['active_form'] = False
        with open(os.path.join(os.getcwd(), app.config['_CACHE_PATH'], uid+"_scm.pickle"), "wb") as outf:
            cPickle.dump(params, outf)
    return redirect(url_for('input', raw_sim=uid))        

@app.route('/output/<raw_sim>')
def output(raw_sim):
    print("Raw Prefix is {}".format(raw_sim[:1000]))
    sim = asciify(raw_sim[:1000])
    print("Adjusted Prefix is {}".format(sim))
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    print("Starting output for prefix {}".format(sim))
    app.logger.info('Starting Output with unique ID %s',sim)
    # Output names
    if not os.path.exists(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle")):
        print("CACHE FILE NOT FOUND!!!!!")
        app.logger.error("Error: Simulation %s not found",sim)
        session['message'] = 'Simulation not found'
        session['description'] = 'Simulation %s not found' % (sim)
        return redirect(url_for('error', raw_sim=sim))
    print("Opening Cache File")
    f = open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"),'rb')
    params = cPickle.load(f)
    f.close()
    print("Loaded Parameter file")
    params['out_prefix'] = sim
    params['in_path'] = os.path.join(os.getcwd(),app.config['_INP_PATH'])
    params['out_path'] = os.path.join(os.getcwd(),app.config['_OUT_PATH'])
    params['version'] = app.config['_VERSION']
    print("Set Current Parameters")
    if 'proxy' in app.config:
        print("Setting parameters for proxy")
        params['progress_page'] = app.config['proxy'] + url_for('progress')
        params['final_page'] = app.config['proxy'] + url_for('final',raw_sim=sim)
        params['static_page'] = app.config['proxy'] + url_for('static',filename='sim_temp/')
    else:
        print("Setting parameters without proxy")
        params['final_page'] = url_for('final',raw_sim=sim,_external=True)
        params['static_page'] = url_for('static',filename='sim_temp/',_external=True)
        params['progress_page'] = url_for('progress')
    print("Creating Task IDs")
    task_ids = [uuid()]
    tasks = [start_sequence.subtask((params,),task_id=task_ids[0])]
    task_ids.append(uuid())
    tasks.append(create_catalogues.subtask(task_id=task_ids[1]))
    task_ids += [uuid() for obs in params['observations']]
    tasks += [observation.subtask((obs,),task_id=id) for obs,id in zip(params['observations'],task_ids[2:])]
    task_ids.append(uuid())
    tasks.append(finalize.subtask((),task_id=task_ids[-1]))
    print("Finished creating {} task IDs".format(len(tasks)))
    task_list = chain(tasks)
    task = task_list.apply_async()
    print("Started Tasks. Saved task file as {}".format(task.id))
    task_file = params['out_prefix']+'_'+task.id
    f = open(os.path.join(os.getcwd(),app.config['_OUT_PATH'],task_file+'.pickle'),'wb')
    cPickle.dump(task_ids,f)
    f.close()
    print("Wrote Task File")
    return redirect('/progress?tid=' + task_file)

@app.route('/final/<raw_sim>')
def final(raw_sim):
    sim = asciify(raw_sim[:1000])
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    app.logger.info('Starting Final with unique ID %s',sim)
    app.logger.info('Looking for %s',os.path.join(os.getcwd(),app.config['_OUT_PATH'],sim+'_final.pickle'))
    if os.path.exists(os.path.join(os.getcwd(),app.config['_OUT_PATH'],sim+'_final.pickle')):
        app.logger.info('Returning result %s',sim)
        f = open(os.path.join(os.getcwd(),app.config['_OUT_PATH'],sim+'_final.pickle'),'rb')
        params = cPickle.load(f)
        f.close()
#         print(params['stop_time'], type(params['stop_time']))
#         print(params['start_time'], type(params['start_time']))
#         (u'2017-07-26T13:15:50.373083', <type 'unicode'>)
        try:
            runtime = params['stop_time'] - params['start_time']
        except TypeError as e:
            params['start_time'] = datetime.datetime.strptime(params['start_time'], '%Y-%m-%dT%H:%M:%S.%f')
            runtime = params['stop_time'] - params['start_time']
        input_names = [os.path.split(cat)[1] for cat in params['catalogues']]
        obs = []
        for obset in params['observations_out']:
            o_s = {'observations': []}
            for ob in obset['observations']:
                o = {}
                o['id'] = ob['id']
                o['observed_names'] = [os.path.split(cat)[1] for cat in ob['observed_catalogues']]
                o['out_fits'] = os.path.split(ob['out_fits'])[1]
                o['out_png'] = os.path.split(ob['out_fits'])[1].replace('.fits','.png')
                o['mosaic_fits'] = []
                o['mosaic_png'] = []
                for mosaic in ob['mosaic_fits']:
                    o['mosaic_fits'].append(os.path.split(mosaic)[1])
                    o['mosaic_png'].append(os.path.split(mosaic)[1].replace('.fits','.png'))
                o['psf_fits'] = os.path.split(ob['psf_fits'])[1]
                o['psf_png'] = o['psf_fits'].replace('.fits','.png')
                o['parsedParam'] = ob['parsedParam']
                o_s['observations'].append(o)
            o_s['mosaics'] = [os.path.split(fname)[1].replace('.fits', '.png') for fname in obset['mosaics']]
            obs.append(o_s)
        return render_template('output.html', time=time.ctime(), version=params['version'], title=params['out_prefix']+" Results", catalogues=input_names,
                               observations=obs, web_path=url_for('static',filename='sim_temp/', ), runtime=runtime, zip_name=params['out_prefix']+'.zip', 
                               telescope=telescope, instrument_intro=instrument_intro, sim=sim, server_mod_time=server_mod_time, stips_version=stips_version, 
                               stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info,
                               email_test=app.config['email_test'])
    elif os.path.exists(os.path.join(os.getcwd(),app.config['_CACHE_PATH']+sim+'_scm.pickle')):
        return redirect(url_for('output',raw_sim=sim))
    else:
        app.logger.info('Result %s not found',sim)
        return render_template('not_found.html',time=time.ctime(),version=params['version'],id=sim,
                               telescope=telescope, instrument_intro=instrument_intro, 
                               server_mod_time=server_mod_time, stips_version=stips_version, 
                               stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, 
                               grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info,
                               email_test=app.config['email_test'])

@app.route('/docs/<raw_page>/<raw_anchor>')
@app.route('/docs/<raw_page>')
@app.route('/docs')
def docs(raw_page='main', raw_anchor=''):
    page = asciify(raw_page[:1000])
    anchor = asciify(raw_anchor[:1000])
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    doc_template = "docs/main.html"
    if "interface" in page:
        doc_template = "docs/interface.html"
    elif "format" in page:
        doc_template = "docs/format.html"
    elif "implementation" in page:
        doc_template = "docs/implementation.html"
    elif "notes" in page:
        doc_template = "docs/notes.html"
    return render_template(doc_template, anchor=anchor, time=time.ctime(), version=app.config['_VERSION'], 
                           telescope=telescope, instrument_intro=instrument_intro, server_mod_time=server_mod_time, 
                           stips_version=stips_version, stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, 
                           grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info, email_test=app.config['email_test'])

@app.route('/progress')
def progress():
    """Shows the progress of the current task or redirect home."""
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    task_id = asciify(request.args.get('tid', '')[:1000])
    return render_template('progress.html', telescope=telescope, instrument_intro=instrument_intro, task_id=task_id, time=time.ctime(),
                           version=app.config['_VERSION'], server_mod_time=server_mod_time, stips_version=stips_version, 
                           stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, grid_pandeia=grid_pandeia_info, 
                           grid_stips=grid_stips_info, email_test=app.config['email_test']) if task_id else redirect('/')

@app.route("/form")
def simulate_form():
    """Called to determine if the current form has been completed"""
    sim = asciify(request.args.get('sim', '')[:1000])
    print("Received Form Query for sim {}".format(sim))
    with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'rb') as inf:
        params = cPickle.load(inf)
    print("Loaded parameters for simulation {}".format(sim))
    ready = False
    if not params['active_form']:
        print("Form no longer active: return true")
        ready = True
    return jsonify(ready=ready)

@app.route('/poll')
def simulate_poll():
    """Called by the progress page using AJAX to check whether the task is complete."""
    task_id = asciify(request.args.get('tid', '')[:1000])
    try:
        f = open(os.path.join(app.config['_OUT_PATH'],task_id+'.pickle'),'rb')
        task_list = cPickle.load(f)
        f.close()
        task_set = [celery.AsyncResult(id) for id in task_list]
    except ConnectionError:
        # Return the error message as an HTTP 500 error
        return 'Could not connect to the task queue. Check to make sure that <strong>redis-server</strong> is running and try again.', 500
    ready = task_set[-1].ready()
    if not ready:
        num_tasks = len(task_set)
        num_ready = 0
        num_working = 0
        working_status = []
        status_string = ""
        for task in task_set:
            status_string += task.task_id + " " + task.status + "\n"
            if task.status == "SUCCESS":
                num_ready += 1
            elif task.status == "PENDING":
                pass
            elif task.status == "FAILURE" or task.status == "FAILED":
                progress = "FAILED"
                working_status = ""
                return jsonify(ready=True,progress=progress,working_status=working_status)
            else: #working
                num_working += 1
                working_status.append(task.status)
        progress = "%d of %d complete, %d working." % (num_ready,num_tasks,num_working)
        working_status = ",".join(working_status)
        app.logger.info(status_string)
        app.logger.info(working_status)
    else:
        progress="COMPLETE"
        working_status = ""
    return jsonify(ready=ready,progress=progress,working_status=working_status)

@app.route('/results')
def simulate_results():
    """When poll_task indicates the task is done, the progress page redirects here using JavaScript."""
    if not check_authorized(request.headers, app.config):
        app.logger.error("Unauthorized User {}".format(request.headers.get("remote-user")))
        session['message'] = "User {} is unauthorized".format(request.headers.get('remote-user'))
        session['description'] = "User {} is not in the authorized users list".format(request.headers.get('remote-user'))
        return redirect(url_for("unauthorized"))
    task_id = asciify(request.args.get('tid', '')[:1000])
    sim_id = task_id[:task_id.find("_")]
    f = open(os.path.join(app.config['_OUT_PATH'],task_id+'.pickle'),'rb')
    task_list = cPickle.load(f)
    f.close()
    task_set = [celery.AsyncResult(id) for id in task_list]
    task = task_set[-1]
    error_message = ""
    if not task.ready():
        if isinstance(task.serializable(), str):
            return redirect('/prograss?tid=' + task.serializable())
        else:
            error_message = ""
            for task_item in task_set:
                if task_item.traceback is not None:
                    error_message += "Traceback %s\n"%(task_item.id) + task_item.traceback + "\n"
    if not task.successful():
        task_name = task_id[:task_id.find("_")]
        error_message = error_message.replace(" ","&nbsp;").replace("\n","<br />")
        app.logger.warning("Reporting Error %s",error_message)
        session['message'] = 'Simulation %s was not successful' % task_name
        session['description'] = 'Simulation %s failed with the Error:<br /><br /> %s' % (task_name, error_message)
        with open(os.path.join(app.config['_CACHE_PATH'],sim_id+'_scm.pickle'),'rb') as f:
            params = cPickle.load(f)
        if params['user']['email'] is not None:
            msg_subject = "Your STIPS simulation %s encountered an error" % (sim_id)
            msg_text = error_template.substitute(id=sim_id, error_message=error_message.replace("&nbsp;", " ").replace("<br />", "\n"))
            result = SendEmail(params['user']['email'], msg_subject, msg_text, [])
            if result != "":
                if 'errors' not in params:
                    params['errors'] = []
                params['errors'].append(result)
        return redirect(url_for('error', raw_sim=task_name))
    params = task.get()
    app.logger.info('Got back %s',str(params))
    app.logger.info('Rendering output page')
    return redirect(url_for('final',raw_sim=params['out_prefix']))

def dither_offsets(dither_pattern):
    ins = instruments[dither_pattern['instrument']]
    print dither_pattern
    print ins
    dither_set = ins.handleDithers(dither_pattern)
    my_dithers = []
    for dx,dy in dither_set:
        my_dithers.append({'offset_ra':dx, 'offset_dec':dy, 'offset_pa':0., 'offset_centre': dither_pattern['centre']})
    return my_dithers

def make_form_html(form, item_type):
    form_html = ""
    for field in form:
        print field.name
        if field.name in ["csrf_token", item_type+"_id", "orig_filename", "current_filename", "sim_prefix"]:
            form_html += "<div class='token_holder' style='display: none;'>{}{}</div>".format(field.label(), field(id=field.name))
        elif isinstance(field, HiddenField):
            form_html += "<div class='token_holder' style='display: none;'>{}{}</div>".format(field.label(), field(id=field.name))
        else:
            form_html += "{} {}<br />".format(field.label(), field)
    return form_html

@app.route('/reset_dither/<sim>/<items>')
def reset_dither(sim, items):
    ins, obs, d_type, d_points, d_size, d_subpixel = items.split("-")
    form = buildDitherForm(sim, ins, obs, d_type, d_points, d_size, d_subpixel)
    template_base = template_classes['dither']
    template = template_classes['dither'].substitute(form_type="dither", name="Dither Pattern", form_html=make_form_html(form, "dither"))
    return json.dumps(template)

@app.route('/new_form/<sim>/<item_type>')
def new_form(sim, item_type):
    with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'rb') as inf:
        params = cPickle.load(inf)
    params['active_form'] = True
    with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'wb') as outf:
        cPickle.dump(params, outf)
    app.logger.info("Item: {}, in Instruments: {}: {}".format(item_type, INSTRUMENTS, item_type in INSTRUMENTS))
    if item_type in INSTRUMENTS:
        form = form_classes['observations'](instrument=item_type)
        item_type = "observations"
    elif 'offset' in item_type:
        items = item_type.split("-")
        form = form_classes['offset'](observation=items[1])
        item_type = "offset"
    elif 'dither' in item_type:
        items = item_type.split("-")
        obs = params['observations'][int(items[1])-1]
        instrument = obs['instrument']
        form = buildDitherForm(sim, instrument, int(items[1]), None, None, None, None)
        item_type = "dither"
    else:
        form = form_classes[item_type]()
    template_base = template_classes[item_type]
    template = template_base.substitute(form_type=item_type, name=template_names[item_type], form_html=make_form_html(form, item_type))
    return json.dumps(template)

@app.route('/get_form/<sim>/<item>')
def get_form(sim, item):
    app.logger.info("get_form received {} for sim {}".format(item, sim))
    items = item.split("-")
    if len(items) == 2:
        item_type, id = items
        obs_id = None
    else:
        obs_id, item_type, id = items[1:]
    app.logger.info("Retrieving {} {} {}".format(sim, item_type, id))
    if os.path.exists(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle")):
        with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'rb') as inf:
            params = cPickle.load(inf)
        params['active_form'] = True
        with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'wb') as outf:
            cPickle.dump(params, outf)
        item_id = int(id)
        if obs_id is not None and len(params['observations']) >= int(obs_id):
            print len(params['observations'][int(obs_id)-1]['offsets'])
            print item_id
            if len(params['observations'][int(obs_id)-1]['offsets']) >= item_id:
                to_return = params['observations'][int(obs_id)-1]['offsets'][item_id-1]
        elif isinstance(params[item_type], dict):
            to_return = params[item_type]
        elif len(params[item_type]) >= item_id:
            to_return = params[item_type][item_id-1]
        else:
            return json.dumps(None)
        print "GOT HERE!!!!"
        form = form_classes[item_type](**to_return)
        template_base = template_classes[item_type]
        template = template_base.substitute(form_type=item_type, name=template_names[item_type], form_html=make_form_html(form, item_type))
        return json.dumps(template)
    return json.dumps(None)

@app.route('/delete_form/<sim>/<item>') 
def delete_form(sim, item):
    items = item.split("-")
    if len(items) == 2:
        item_type, id = items
        obs_id = None
    else:
        obs_id, item_type, id = items[1:]
    app.logger.info("Delete {} {} {}".format(sim, item_type, id))
    result = {}
    result['result'] = 'failure'
    if os.path.exists(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle")):
        with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'rb') as inf:
            params = cPickle.load(inf)
        item_id = int(id)
        if obs_id is not None and len(params['observations']) >= int(obs_id):
            if len(params['observations'][int(obs_id)-1]['offsets']) >= item_id:
                del params['observations'][int(obs_id)-1]['offsets'][item_id-1]
            for i, offset in enumerate(params['observations'][int(obs_id)-1]['offsets']):
                offset['offset_id'] = i+1
        elif isinstance(params[item_type], dict):
            params[item_type] = form_classes[item_type]().data
        elif len(params[item_type]) >= item_id:
            if item_type in ["in_imgs", "in_cats"]:
                os.remove(os.path.join(app.config['_OUT_PATH'], params[item_type][item_id-1]['current_filename']))
            del params[item_type][item_id-1]
            for i in range(len(params[item_type])):
                params[item_type][i][item_type+"_id"] = i+1
        else:
            return result
        params['active_form'] = False
        with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), 'wb') as outf:
            cPickle.dump(params, outf)
    result['result'] = 'success';
    return json.dumps(result)

def handle_form_upload(obj_response, files, form_values):
    print("Form Values: {}".format(form_values))
    item_type = search_form(form_values)
    sim = ""
    if "sim_prefix" in form_values:
        sim = form_values["sim_prefix"][0]
    cache_file = "{}_scm.pickle".format(sim)
    print("Simulation: {}, form type: {}".format(sim, item_type))
    form = form_classes[item_type](**form_values)
    print("At least we got here?")
    print("DATA: {}".format(form.data))
    print("DID WE GET HERE?")
    try:
        print("Testing Form Validation")
        test = form.validate()
    except Exception, e:
        print("Form Validation encountered an Exception")
        app.logger.error("Form failed validation with error {}".format(str(e)))
    print("Form {} validates: {}".format(form.data, form.validate()))
    if form.validate():
        current_data = form.data
        if item_type == "previous":
            sim_repeat = current_data["prevsim"]
            if os.path.exists(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim_repeat+"_scm.pickle")):
                with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim_repeat+"_scm.pickle"), "rb") as inf:
                    params = cPickle.load(inf)
                params['user']['email'] = ""
                params['user']['id'] = 1
                params['user']['update_user'] = 'no'
                params['uid'] = sim
                with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],sim+"_scm.pickle"), "wb") as outf:
                    cPickle.dump(params, outf)
                if form.action.data == "Running Again":
                    obj_response.redirect("/output/{}".format(sim))
                    return
                elif form.action.data == "Displaying Final Result":
                    obj_response.redirect("/final/{}".format(sim_repeat))
                    return
                obj_response.redirect("/{}".format(sim))
                return
        elif item_type == "user":
            current_data['update_user'] = 'yes'
        elif item_type in ["in_imgs", "in_cats"]:
            print("Files: {}".format(files))
            if "file" in files:
                file_data = files['file']
                print("File Data: {}".format(file_data))
                filename = secure_filename(file_data.filename)
                current_data['orig_filename'] = filename
                current_data['current_filename'] = sim+"_"+filename
                current_data['file_path'] = app.config['_OUT_PATH']
                file_data.save(os.path.join(app.config['_OUT_PATH'],sim+"_"+filename))
        with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],cache_file), 'rb') as inf:
            params = cPickle.load(inf)
        print("Initial Parameters: {}".format(params))
        if item_type == "offset":
            existing_data = params['observations'][int(current_data['observation'])-1]['offsets']
            print "Current Data: {}".format(current_data)
            print "Existing Data: {}".format(existing_data)
            if len(current_data['offset_id']) > 0 and (0 <= int(current_data['offset_id']) <= len(existing_data)):
                existing_data[int(current_data['offset_id'])-1] = current_data
            else:
                print "GOT HERE WITH FALSE!"
                existing_data.append(current_data)
            for i, offset in enumerate(existing_data):
                offset['offset_id'] = i+1
        elif item_type == "dither":
            existing_data = params['observations'][int(current_data['observation'])-1]['offsets']
            current_data = dither_offsets(current_data)
            print "GOT HERE!!!"
            existing_data.extend(current_data)
            for i, offset in enumerate(existing_data):
                offset['offset_id'] = i+1
        elif isinstance(params[item_type], dict):
            params[item_type] = current_data
        else:
            if item_type in ["in_imgs", "in_cats"] and "file" in current_data:
                del current_data["file"]
            id = -1
            if len(current_data[item_type+"_id"]) > 0:
                id = int(current_data[item_type+"_id"])
            if id > 0 and id <= len(params[item_type]):
                if "orig_filename" in params[item_type][id-1]:
                    os.remove(os.path.join(app.config['_OUT_PATH'], params[item_type][id-1]['current_filename']))
                if item_type == "observations":
                    current_data["offsets"] = params[item_type][id-1]["offsets"]
                params[item_type][id-1] = current_data
            else:
                if item_type == "observations":
                    if current_data['default']:
                        current_data["offsets"] = [{'offset_ra': 0., 'offset_dec': 0., 'offset_pa': 0., 'offset_centre': False,
                                                    'offset_id': "1"}]
                    else:
                        current_data["offsets"] = []
                params[item_type].append(current_data)
            for i in range(len(params[item_type])):
                params[item_type][i][item_type+"_id"] = i+1
        params['active_form'] = False
        print("Final Parameters: {}".format(params))
        with open(os.path.join(os.getcwd(),app.config['_CACHE_PATH'],cache_file), 'wb') as outf:
            cPickle.dump(params, outf)
#         print("Finished Dumping Parameters")
#         obj_response.html("form_status", "<h2>Done</h2>")
#         print("Changed form status to Done")
#         obj_response.attr("form_submit_button", "val", "Done")
#         print("Changed Form Submit Button to Done")
#         obj_response.attr("#add_item_form", "modal", "hide")
#         obj_response.script("location.reload(true);")
#         obj_response.call("reload_page", [])
#         print("Hid the addition form")
        return
    print("Form Errors: {}".format(form.errors))
    error_str = ""
    for i, error in enumerate(form.errors):
        if i != 0:
            error_str += ","
        error_str += "{}: {}".format(error, " ".join(form.errors[error]))
    obj_response.script("error_text('{}');".format(error_str))

# Errors
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', telescope=telescope, instrument_intro=instrument_intro, message='Not Found', 
                           description='The requested URL was not found on the server.', server_mod_time=server_mod_time, stips_version=stips_version, 
                           stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info,
                           email_test=app.config['email_test']), 404

@app.errorhandler(ConnectionError)
def page_not_found(e):
    debug_description = "<strong>redis-server</strong> is"
    production_description = "both <strong>redis-server</strong> and <strong>worker.py</strong> are"
    description = "Check to make sure that %s running." % (debug_description if app.debug else production_description)
    return render_template('error.html', telescope=telescope, instrument_intro=instrument_intro,
                           message='Coult not connect to the task queue', description=description, 
                           server_mod_time=server_mod_time, stips_version=stips_version, stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, 
                           grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info, email_test=app.config['email_test']), 500

@app.route('/error/')
@app.route('/error/<raw_sim>')
def error(raw_sim=None):
    app.logger.info("Sim ID is {} (type {})".format(raw_sim, type(raw_sim)))
    if isinstance(raw_sim, str) or isinstance(raw_sim, unicode):
        sim = asciify(raw_sim[:1000])
    else: #raw_sim is None
        sim = "None"
    app.logger.error('Rendering error page')
    return render_template('error.html', telescope=telescope, instrument_intro=instrument_intro, message=session['message'],
                           description=session['description'],time=time.ctime(),version=app.config['_VERSION'], sim=sim, 
                           server_mod_time=server_mod_time, stips_version=stips_version, stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, 
                           grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info, email_test=app.config['email_test'])

@app.route('/unauthorized/')
def unauthorized():
    app.logger.error("Unauthorized user attempted to connect")
    return render_template('unauthorized.html', telescope=telescope, instrument_intro=instrument_intro,
                           message=session['message'], description=session['description'], time=time.ctime(),
                           version=app.config['_VERSION'], server_mod_time=server_mod_time, stips_version=stips_version, 
                           stips_mod_time=stips_mod_time, pandeia_version=pandeia_version_info, 
                           grid_pandeia=grid_pandeia_info, grid_stips=grid_stips_info, email_test=app.config['email_test'])

def check_authorized(headers, config):
    print "Checking for database at {}".format(os.path.join(config['_INP_PATH'], 'override_users.db'))
    internal_value = headers.get("stsci-internal", u"0")[:1000]
    internal_quoted = asciify(internal_value)
    safe_internal = filter(str.isalnum, internal_quoted)
    print "Safe Internal Value is: {} (type {})".format(safe_internal, type(safe_internal))
    if config['internal_only'] == "1" and asciify(headers.get("stsci-internal", '0')[:1000]) != "1":
        print "User is not internal: unauthorized"
        return False
    if config['check_group'] == "0":
        print "Group validation not required: authorized"
        return True
    for group in config['allowed_groups']:
        if group in headers and str(asciify(headers.get(group, 'false')[:1000])).lower() == "true":
            print "User is member of allowed group {}: authorized".format(group)
            return True
    print "User failed group validation"
    if os.path.exists(os.path.join(config['_INP_PATH'], 'override_users.db')):
        print "User Override Database Found"
        remote_user = asciify(headers.get('remote-user', '')[:1000])
        print "Email is '{}'".format(remote_user)
        db = sqlite3.connect(os.path.join(config['_INP_PATH'], 'override_users.db'))
        c = db.cursor()
        res = c.execute("""SELECT * FROM override_users WHERE user_email = ?""", (remote_user,)).fetchall()
        print "Database result is {}".format(res)
        db.close()
        if len(res) > 0:
            print "OVERRIDE: User {} is allowed".format(remote_user)
            return True
    print "User Unauthorized"
    return False

def search_form(form_values):
    keys = form_values.keys()
    for key in keys:
        if "_" in key:
            items = key.split("_")
            if items[-1] == "id":
                return "_".join(items[:-1])
    return ""

def asciify(input):
    if isinstance(input, unicode):
        return unicodedata.normalize('NFKD', input).encode('ascii', 'ignore')
    elif not isinstance(input, str):
        return "{}".format(input)
    return input

def ascii_email(input):
    filter = re.compile(r"[^a-zA-Z0-9@._']")
    return re.sub(filter, '', input)

app.secret_key = app.config['SECRET_KEY']

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("-p","--port",action="store",dest="port",default=9090,metavar="PORT",help="Server port")
    parser.add_argument("-f","--file",action="store",dest="logfile",default="simulator.log",metavar="FILE",help="Logging file name")
    results = parser.parse_args()
    
    debug = app.config.get('DEBUG', True)
    use_reloader = app.config.get('DEBUG', True)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler = logging.FileHandler(os.path.join(os.getcwd(),results.logfile))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    loggers = [app.logger]
    for logger in loggers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)
    if debug:
        app.debug_log_format = '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'    
    app.run(host=app.config.get('HOST', 'localhost'), port=app.config.get('PORT', int(results.port)), debug=debug, use_reloader=use_reloader)
