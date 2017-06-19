--------------------------------------------------------------------------------
1. Start local web server

   python webserver.py

2. Point browser to URL below

   http://localhost:8000/cgi-bin/webbsim.py

3. CTRL+C to stop web server

4. Temporary output files (need manual deletion) are

   http://localhost:8000/sim*
   -- OR --
   /grp/jwst/wmo/lim/scripts_cgi/sim*

5. Use this to remove temporary output files (replace with cron job?)

   cleansim

--------------------------------------------------------------------------------
CGI uses scripts and data in:
    /user/lim/python/lib/
    /grp/jwst/wmo/lim/scripts_cgi/sim_input/
    /grp/jwst/wmo/lim/scripts_new/lib/
        (except ConvertUnit.py)
    /grp/jwst/wmo/lim/scripts_new/psf_data/

CGI stores results in:
    /grp/jwst/wmo/lim/scripts_cgi/sim_temp/

--------------------------------------------------------------------------------
Old copies:

    /grp/jwst/wmo/lim/scripts_cgi_old120131.tar

--------------------------------------------------------------------------------
STScI Web Server (ISSUE=9884 PROJ=Computer Support) notes:

Machines: pljesse (test), plbilly (prod)

Machines are RHEL6 with Apache 2.2 (as of Feb 2012).
Environment has to be changed separately on each machine.

Cronjob to delete test and prod sim_temp/sim* files are on pljesse under lim.

/home/lim
    |
    -- jwstwebsim -> /grp/websites/jwstwebsim/
        |
        -- prod is the document root for jwstwebsim.stsci.edu
        |
        -- test is the document root for jwstwebsim-test.stsci.edu

Codes could be different between scripts_cgi, test, and prod.
Do diff to make sure before copying!

--------------------------------------------------------------------------------
