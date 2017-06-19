from flask_wtf import Form
from flask_wtf.file import FileField,FileAllowed
from wtforms import (BooleanField, FloatField, FormField, FieldList, HiddenField, 
     IntegerField, SelectMultipleField, SubmitField, TextField, widgets, validators)
from wtforms.compat import text_type
from wtforms_components import read_only, SelectField

import glob, importlib, inspect, os, sys, wtforms

from stips.utilities import InstrumentList

import DefaultSettings

unit_choices =  [
                    ("c","Count/s"),
                    ("j","Jansky"),
                    ("e","erg/s"),
                    ("p","photons/s"),
                    ("s","W/m/m^2/Sr")
                ]

imf_choices =   [
                    ("powerlaw","Power Law with alpha ="),
                    ("kroupa","Kroupa"),
                    ("salpeter","Salpeter"),
                    ("schechter","Schechter"),
                    ("modified_schechter","Schechter with Exponential Cut-off")
                ]

distribution_choices =  [
                            ("exp","Exponential"),
                            ("invpow","Inverse Power Law"),
                            ("regpow","Power Law"),
                            ("uniform","Uniform")
                        ]


class NonValidatingSelectField(SelectField):
    def pre_validate(self, form):
        pass

class MulticolumnTableWidget(widgets.TableWidget):
    """
    As TableWidget, but allows for a multi-column table.
    """
    def __init__(self, with_table_tag=True, columns=1):
        self.columns = columns
        super(MulticolumnTableWidget,self).__init__(with_table_tag)
    
    def __call__(self,field,**kwargs):
        html = []
        if self.with_table_tag:
            kwargs.setdefault('id', field.id)
            html.append('<table %s>' % (widgets.html_params(**kwargs)))
        hidden = ''
        column_count = 0
        for subfield in field:
            if subfield.type == 'HiddenField':
                hidden += text_type(subfield)
            else:
                if column_count == 0:
                    html.append('<tr>')
                html.append('<td>%s%s</td><th>%s</th>' % (text_type(subfield), hidden, text_type(subfield.label)))
                column_count += 1
                if column_count == self.columns:
                    column_count = 0
                    html.append('</tr>')
        if self.with_table_tag:
            html.append('</table>')
        if hidden:
            html.append(hidden)
        return widgets.HTMLString(''.join(html))
    
class MultiCheckboxField(SelectMultipleField):
    widget = MulticolumnTableWidget(columns=7)
    option_widget = widgets.CheckboxInput()
    def pre_validate(self, form):
        pass

class FormattedFloatField(FloatField):
    def _value(self):
        if self.raw_data:
            return "{:e}".format(self.raw_data[0])
        elif self.data is not None:
            return unicode("{:e}".format(self.data))
        else:
            return u''

class GreaterThan(object):
    """
    Compares the value of two fields the value of self is to be greater than the supplied field.

    :param fieldname:
        The name of the other field to compare to.
    :param message:
        Error message to raise in case of a validation error. Can be
        interpolated with `%(other_label)s` and `%(other_name)s` to provide a
        more helpful error.
    """
    def __init__(self, fieldname, message=None):
        self.fieldname = fieldname
        self.message = message

    def __call__(self, form, field):
        try:
            other = form[self.fieldname]
        except KeyError:
            raise validators.ValidationError(field.gettext(u"Invalid field name '%s'.") % self.fieldname)
        if field.data != '' and field.data < other.data:
            d = {
                'other_label': hasattr(other, 'label') and other.label.text or self.fieldname,
                'other_name': self.fieldname
            }
            if self.message is None:
                self.message = field.gettext(u'Field must be greater than %(other_name)s.')

            raise validators.ValidationError(self.message % d)

class BaseForm(Form):
    def __iter__(self):
        field_order = getattr(self, 'field_order', None)
        if field_order:
            temp_fields = []
            for name in field_order:
                if name == '*':
                    temp_fields.extend([f for f in self._unbound_fields if f[0] not in field_order])
                else:
                    temp_fields.append([f for f in self._unbound_fields if f[0] == name][0])
            self._unbound_fields = temp_fields
        return super(BaseForm, self).__iter__()

class RecallForm(BaseForm):
    prevsim = TextField(u"Recall Simulation: ", validators=[validators.Required()])
    action = SelectField(u"Process by: ", default="Running Again", choices=[("Running Again", "Running Again"), 
                                                                            ("Editing", "Editing"), 
                                                                            ("Displaying Final Result", "Displaying Final Result")])
    previous_id = HiddenField(default='')
    sim_prefix = HiddenField()
    field_order = ('prevsim', 'action', 'previous_id')

class UserForm(BaseForm):
    email = TextField(u'Email Address', validators=[validators.Email(),validators.Optional()])
    user_id = HiddenField(default='1')
    save_user = BooleanField(u'Save E-mail Address', default=True)
    update_user = HiddenField(default='no')
    sim_prefix = HiddenField()

class SceneForm(BaseForm):
    seed = IntegerField(u'Random Number Seed', default=1234, validators=[validators.Required()])
    ra = FloatField(u"RA (decimal degrees)",default=0.0,validators=[validators.NumberRange(min=0.,max=360.)])
    dec = FloatField(u"DEC (decimal degrees)",default=0.0,validators=[validators.NumberRange(min=-90.,max=90.)])
    scene_general_id = HiddenField(default='1')
    field_order = ('seed', 'ra', 'dec', 'scene_general_id')
    sim_prefix = HiddenField()

class BackgroundImageForm(BaseForm):
    file = FileField(u"Background FITS Image", validators=[FileAllowed(['fits'],"FITS Files Only")])
    orig_filename = HiddenField()
    current_filename = HiddenField()
    file_path = HiddenField()
    in_imgs_id = HiddenField(default='')
    units = SelectField(u"Image Units", default=u"s", choices=unit_choices)
    scale = FloatField(u"Pixel Scale",default=0.1)
    wcs = BooleanField(u"Take WCS from File",default=False)
    poisson = BooleanField(u"Add Poisson Noise",default=True)
    ext = IntegerField(u"Image Extension", default=1)
    sim_prefix = HiddenField()
    field_order = ('file', 'orig_filename', 'current_filename', 'units', 'scale', 'wcs', 'poisson', 'ext', 'in_imgs_id', 'sim_prefix')

class InputCatalogueForm(BaseForm):
    file = FileField(u"Input Catalogue")
    orig_filename = HiddenField()
    current_filename = HiddenField()
    file_path = HiddenField()
    in_cats_id = HiddenField(default='')
    sim_prefix = HiddenField()
    field_order = ('file', 'orig_filename', 'current_filename', 'in_cats_id', 'sim_prefix')

class StellarForm(BaseForm):
    n_stars = IntegerField(u"Number of Stars",default=50000,validators=[validators.NumberRange(min=0,max=1000000000)])
    z_low = FloatField(u"[Fe/H] Lower Bound",default=0.0,validators=[validators.NumberRange(min=-2.2,max=0.5)])
    z_high = FloatField(u"[Fe/H] Upper Bound",default=0.0,validators=[validators.NumberRange(min=-2.2,max=0.5),GreaterThan('z_low')])
    age_low = FormattedFloatField(u"Age Lower Bound",default=1.0e9,validators=[validators.NumberRange(min=1.e6,max=1.35e10)])
    age_high = FormattedFloatField(u"Age Upper Bound",default=1.0e9,validators=[validators.NumberRange(min=1.e6,max=1.35e10),GreaterThan('age_low')])
    imf = SelectField(u"IMF",default="salpeter",choices=imf_choices)
    alpha = FloatField(u"Power Law Order",default=-2.35,validators=[validators.NumberRange(min=-3.,max=-1.)])
    binary_fraction = FloatField(u"Binary Fraction",default=0.1,validators=[validators.NumberRange(min=0.,max=1.)])
    distribution = SelectField(u"Distribution",default="invpow",choices=distribution_choices)
    clustered = BooleanField(u"Move Higher-mass Stars Closer to Centre",default=True)
    radius = FloatField(u"Radius",default=10.0)
    radius_units = SelectField(u"Radius Units",default=u"pc",choices=[("pc","pc"),("arcsec","arcsec")])
    offset_ra = FloatField(u"RA Offset (mas)",default=0.0)
    offset_dec = FloatField(u"DEC Offset (mas)",default=0.0)
    distance_low = FloatField(u"Distance Lower Bound (kpc)",default=20.0,validators=[validators.NumberRange(min=1.e-3,max=4.2e6)])
    distance_high = FloatField(u"Distance Upper Bound (kpc)",default=20.0,validators=[validators.NumberRange(min=1.e-3,max=4.2e6),GreaterThan('distance_low')])
    stellar_id = HiddenField(default='')
    sim_prefix = HiddenField()

class GalaxyForm(BaseForm):
    n_gals = IntegerField(u"Number of Galaxies",default=100,validators=[validators.NumberRange(min=0,max=5000)])
    z_low = FloatField(u"Redshift Lower Bound",default=0.,validators=[validators.NumberRange(min=0.,max=10.)])
    z_high = FloatField(u"Redshift Upper Bound",default=0.,validators=[validators.NumberRange(min=0.,max=10.),GreaterThan('z_low')])
    rad_low = FloatField(u"Half-light Radius Lower Bound",default=0.01,validators=[validators.NumberRange(min=1.e-3,max=2.)])
    rad_high = FloatField(u"Half-light Radius Upper Bound",default=2.,validators=[validators.NumberRange(min=1.e-3,max=2.),GreaterThan('rad_low')])
    vmag_low = FloatField(u"Apparent VMAG lower bound",default=25.,validators=[validators.NumberRange(min=12.,max=30.),GreaterThan('vmag_high')])
    vmag_high = FloatField(u"Apparent VMAG upper bound",default=15.,validators=[validators.NumberRange(min=12.,max=30.)])
    distribution = SelectField(u"Distribution",default="uniform",choices=distribution_choices)
    clustered = BooleanField(u"Move Higher-mass Galaxies Closer to Centre",default=False)
    radius = FloatField(u"Radius",default=600.0)
    radius_units = SelectField(u"Radius Units",default=u"pc",choices=[("pc","pc"),("arcsec","arcsec")])
    offset_ra = FloatField(u"RA Offset (arcsec)",default=0.0)
    offset_dec = FloatField(u"DEC Offset (arcsec)",default=0.0)
    galaxy_id = HiddenField(default='')
    sim_prefix = HiddenField()

class OffsetForm(Form):
    offset_ra = FloatField(u"RA Offset (arcsec)",default=0.0)
    offset_dec = FloatField(u"DEC Offset (arcsec)",default=0.0)
    offset_pa = FloatField(u"PA Offset (degrees)",default=0.0,validators=[validators.NumberRange(min=-360.,max=360.)])
    offset_centre = BooleanField(u"Centre Offset on Detector V2/V3 Position",default=False)
    offset_id = HiddenField(default='')
    sim_prefix = HiddenField()
    observation = HiddenField()

class DitherForm(Form):
    instrument = HiddenField()
    observation = HiddenField()
    centre = BooleanField(u"Centre Dither on Detector V2/V3 Position")
    dither_type = SelectField()
    dither_points = SelectField()
    dither_size = SelectField()
    dither_subpixel = SelectField()
    dither_id = HiddenField(default='')
    sim_prefix = HiddenField()
    def __init__(self, *args, **kwargs):
        super(DitherForm, self).__init__(*args, **kwargs)
        self.dither_type.choices = self.get_dither_type
        self.dither_size.choices = self.get_dither_size
        self.dither_points.choices = self.get_dither_points
        self.dither_subpixel.choices = self.get_dither_subpixel
    def get_dither_type(self):
        return [(x, x.title()) for x in DefaultSettings.instruments[self.instrument.data].DITHERS]
    def get_dither_points(self):
        return [(x, x) for x in DefaultSettings.instruments[self.instrument.data].DITHER_POINTS[self.dither_type.data]]
    def get_dither_size(self):
        return [(x, x.title()) for x in DefaultSettings.instruments[self.instrument.data].DITHER_SIZE[self.dither_type.data]]
    def get_dither_subpixel(self):
        return [(x, x) for x in DefaultSettings.instruments[self.instrument.data].DITHER_SUBPIXEL[self.dither_type.data]]

def buildDitherForm(sim, ins, obs, dither_type=None, dither_points=None, dither_size=None, dither_subpixel=None):
    class DitherForm(Form):
        pass

    DitherForm.instrument = HiddenField(default=ins)
    DitherForm.centre = BooleanField(u"Centre Dither Offsets on Detector V2/V3 Position", default=False)
    DitherForm.dither_id = HiddenField(default='')
    DitherForm.sim_prefix = HiddenField(default=sim)
    DitherForm.observation = HiddenField(default=obs)
    choices = [(x, x.title()) for x in DefaultSettings.instruments[ins].DITHERS]
    dither_type_default = choices[0][0]
    if dither_type is not None:
        dither_type_default = dither_type
    DitherForm.dither_type = SelectField(u"Dither Type", choices=choices, default=dither_type_default)
    choices = [(x, x) for x in DefaultSettings.instruments[ins].DITHER_POINTS[dither_type_default]]
    default = choices[0][0]
    if dither_points is not None and dither_points in [x[0] for x in choices]:
        default = dither_points
    DitherForm.dither_points = SelectField(u"Dither Points", choices=choices, default=default)
    choices = [(x, x.title()) for x in DefaultSettings.instruments[ins].DITHER_SIZE[dither_type_default]]
    default = choices[0][0]
    if dither_size is not None and dither_size in [x[0] for x in choices]:
        default = dither_size
    DitherForm.dither_size = SelectField(u"Dither Size", choices=choices, default=default)
    choices = [(x, x) for x in DefaultSettings.instruments[ins].DITHER_SUBPIXEL[dither_type_default]]
    default = choices[0][0]
    if dither_subpixel is not None and dither_subpixel in [x[0] for x in choices]:
        default = dither_subpixel
    DitherForm.dither_subpixel = SelectField(u"Subpixel Dither", choices=choices, default=default)
    return DitherForm()

class ObservationForm(Form):
    instrument = HiddenField()
    detectors = NonValidatingSelectField("Detectors to Include")
    default = BooleanField(u"Include Centred Exposure", default=True)
    exptime = FloatField(u"Exposure Time",default=1000.0,validators=[validators.NumberRange(min=1.,max=10000.)])
    coadd = IntegerField(u"Co-added Exposures",default=1,validators=[validators.NumberRange(min=1,max=10000)])
    filters = MultiCheckboxField(u"Filters")
    oversample = IntegerField(u"Oversample Image By",default=1,validators=[validators.NumberRange(min=1,max=20)])
    pupil_mask = TextField(u"PSF Pupil Mask",default="",validators=[validators.Optional()])
    background = SelectField(u"Background")
    distortion = BooleanField(u"Include Image Distortion", default=False)
    observations_id = HiddenField(default='')
    sim_prefix = HiddenField()
    def __init__(self, *args, **kwargs):
        super(ObservationForm, self).__init__(*args, **kwargs)
        
        instruments = DefaultSettings.instruments
        
        self.filters.choices = [(x, x) for x in instruments[self.instrument.data].FILTERS]
        self.background.choices = [(x, y) for x, y in zip(instruments[self.instrument.data].BACKGROUNDS_V, 
                                                          instruments[self.instrument.data].BACKGROUNDS)]
        self.background.default = self.background.choices[0][0]
        self.detectors.choices = [(x, x) for x in instruments[self.instrument.data].N_DETECTORS]
    def validate_detectors(self, field):
        if field.data not in [str(x) for x in DefaultSettings.instruments[self.instrument.data].N_DETECTORS]:
            raise ValidationError("Detectors must be one of {}".format(instruments[self.instrument.data].N_DETECTORS))

class ResidualForm(Form):
    flatfield = BooleanField(u"Flatfield Residual",default=True,validators=[validators.Optional()])
    dark = BooleanField(u"Dark Residual",default=True,validators=[validators.Optional()])
    cosmic = BooleanField(u"Cosmic Ray Residual",default=True,validators=[validators.Optional()])
    residual_id = HiddenField(default='')
    sim_prefix = HiddenField()

form_classes = {
                    'previous': RecallForm,
                    'user': UserForm,
                    'scene_general': SceneForm,
                    'in_imgs': BackgroundImageForm,
                    'in_cats': InputCatalogueForm,
                    'stellar': StellarForm,
                    'galaxy': GalaxyForm,
                    'offset': OffsetForm,
                    'dither': DitherForm,
                    'observations': ObservationForm,
                    'residual': ResidualForm
               }

class ParameterForm(Form):
    user = FormField(UserForm)
    scene_general = FormField(SceneForm)
    in_imgs = FieldList(FormField(BackgroundImageForm))
    in_cats = FieldList(FormField(InputCatalogueForm))
    stellar = FieldList(FormField(StellarForm))
    galaxy = FieldList(FormField(GalaxyForm))
    observations = FieldList(FormField(ObservationForm))
    residual = FormField(ResidualForm)
