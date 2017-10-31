"""
General CGI form functions.

:Author: Pey Lian Lim

:Organization: Space Telescope Science Institute

:History:
    * 2010/10/27 PLL created this module.
    * 2011/07/12 PLL applied v0.4 updates.
"""

# External modules
import f2n, numpy, os, sys, time

from astropy.io import fits as pyfits
from email.mime.image import MIMEImage
from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart
from validate_email import validate_email
import smtplib

#-----------
def MakeSelect(name,toggle,values,default):
    """
    Creates an HTML <select> input.
    
        name : the HTML name and id of the select
        values : the available options for the select
        default : the default value of the select
    """
    html_str = "<select name='%s' id='%s' data-toggle='%s'>" % (name,name,toggle)
    for value in values:
        if value == default:
            html_str += "<option value='%s' selected='selected'>%s</option>" % (value,value)
        else:
            html_str += "<option value='%s'>%s</option>" % (value,value)
    html_str += "</select>"
    return html_str

#-----------
def Fits2Png(fitsFile, pngFile, pngTitle='', cbarLabel='', scale='lin'):
    """
    Save FITS as PNG for display.

    Parameters
    ----------
    fitsFile: string
        Input FITS file.

    pngFile: string
        Output PNG file.

    pngTitle: string, optional
        Plot title.

    cbarLabel: string, optional
        Colorbar label.
    """

    # Read image
    img = f2n.fromfits(fitsFile)
    binfactor = min(int(round(max(img.origwidth,img.origheight)/800)),1)
    try:
        img.setzscale()
    except Exception, e:
        pass
    img.rebin(binfactor)
    img.makepilimage(scale,negative=False)
    img.writetitle(pngTitle)
    img.tonet(pngFile)

#-----------
def RandomPrefix(id='sim'):
    """
    Generate random prefix for outputs.

    Parameters
    ----------
    id: string
        ID of prefix.

    Returns
    -------
    pfx: string
        `idN` where `N` is a random integer
        determined by current time.
    """
    pfx = '%s%.0f%d' % (id, time.time(), os.getpid())
    return pfx

#-----------
def SendEmail(msg_to, msg_subject, msg_text, msg_attach):
    """
    Send an e-mail

    """
    output = ""
    try:
        if validate_email(msg_to):
            msg = MIMEMultipart()
            msg['Subject'] = msg_subject
            msg['From'] = "stips@stsci.edu"
            msg['To'] = msg_to
            msg.attach(MIMEText(msg_text))
            for fname in msg_attach:
                with open(fname, 'rb') as in_file:
                    img = MIMEImage(in_file.read())
                    msg.attach(img)
            s = smtplib.SMTP('smtp.stsci.edu')
            s.sendmail('stips@stsci.edu',[msg_to], msg.as_string())
            s.quit()
    except Exception as e:
        output = str(e)
    return output
