from string import Template

DitherTemplate = Template("""
<div class="modal-header">
	<button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
	<h2>$name</h2>
</div>
<form class="form-horizontal" action="" method="POST" id="add_form" enctype="multipart/form-data">
    <div class="modal-body">
        <div class="container" id="form_status">
        </div>
        <div class="container" id="form_errors">
        </div>
	    <div class="container">
		    $form_html
    	</div>
    </div>
    <div class="modal-footer">
        <input type="submit" id="form_submit_button" class="btn btn-primary btn-success" value="Save" onclick="update_status();" />
        <input type="button" class="btn btn-default" data-dismiss="modal" id="form_cancel_button" value="Cancel" />
        <script>
    	function reset_dither_form()
	    {
		    var sim_value = $$("#sim_value").html();
    		var ins_value = $$("#instrument").val()
	    	var obs_value = $$("#observation").val();
		    var dither_type = $$("#dither_type").val();
    		var dither_points = $$("#dither_points").val();
	    	var dither_size = $$("#dither_size").val();
		    var dither_subpixel = $$("#dither_subpixel").val();
    		var item_list = [ins_value, obs_value, dither_type, dither_points, dither_size, dither_subpixel]
	    	$$.getJSON(
		    	"/reset_dither/" + sim_value + "/" + item_list.join("-"),
			    {}
    		).done(function(data){
        		$$("#form_box_id").html(data);
    	    	$$("#add_item_form").modal('show');
    		    $$("#sim_prefix").val($$("#sim_value").html());
        		sjxUpload.registerForm({"callback": "add_form_upload", "formId": "add_form"});
	    	});
    	}
        $$("#dither_type").change(function() {
            reset_dither_form();});
        $$("#dither_points").change(function() {
            reset_dither_form();});
        $$("#dither_size").change(function() {
            reset_dither_form();});
        $$("#dither_subpixel").change(function() {
            reset_dither_form();});
        </script>
    </div>
</form>
""")

GenericTemplate = Template("""
<div class="modal-header">
	<button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
	<h2>$name</h2>
</div>
<form class="form-horizontal" action="" method="POST" id="add_form" enctype="multipart/form-data">
    <div class="modal-body">
        <div class="container" id="form_status">
        </div>
        <div class="container" id="form_errors">
        </div>
	    <div class="container">
		    $form_html
    	</div>
    </div>
    <div class="modal-footer">
        <input type="submit" id="form_submit_button" class="btn btn-primary btn-success" value="Save" onclick="update_status();" />
        <input type="button" class="btn btn-default" data-dismiss="modal" id="form_cancel_button" value="Cancel" />
    </div>
</form>
""")

template_classes = {
                        'previous': GenericTemplate,
                        'user': GenericTemplate,
                        'scene_general': GenericTemplate,
                        'in_imgs': GenericTemplate,
                        'in_cats': GenericTemplate,
                        'stellar': GenericTemplate,
                        'galaxy': GenericTemplate,
                        'offset': GenericTemplate,
                        'dither': DitherTemplate,
                        'observations': GenericTemplate,
                        'residual': GenericTemplate
                   }
template_names = {
                    'previous': 'Previous Simulation',
                    'user': 'User Information',
                    'scene_general': 'General Scene Parameters',
                    'in_imgs': 'Background Image',
                    'in_cats': 'Input Catalogue',
                    'stellar': 'Stellar Population',
                    'galaxy': 'Galaxy Population',
                    'offset': "Exposure",
                    'dither': "Dither Pattern",
                    'observations': "Observation",
                    'residual': 'Error Residuals'
                 }

start_email = Template("Your simulation has started. You will receive another e-mail when it has completed.\n\n"
                       "To see the status of your simulation, visit <$progress_page?tid=$task_file>.\n\n"
                       "Thank you for using STIPS.\n\n"
                       "Note that this is a send-only e-mail address and won't receive any response."
                       "If you have any comments or questions, please e-mail <york@stsci.edu>")

done_email = Template("Your simulation has now completed. The result files can be found at the following link:\n\n"
                      "Overall: <$final_page>\n\n"
                      "Combined zip file: <$zip>\n\n"
                      "Input Catalogues:\n$inputs\n"
                      "Mosaics:\n$mosaics\n"
                      "Observations:\n$observations\n"
                      "Thank you for using STIPS.\n\n"
                       "Note that this is a send-only e-mail address and won't receive any response."
                       "If you have any comments or questions, please e-mail <york@stsci.edu>")

observation_done_template = Template("Observation $id\n\n"
                                     "\tFITS Image: <$static$fits>\n"
                                     "\tObserved Catalogues:\n$cats\n")

error_template = Template("Your STIPS simulatio $id encountered an error. The following error codes were produced:\n\n$error_message\n")

# Introductory HTML
instrument_intro_template =  {
                        'WFIRST': """The STIPS (Space Telescope Image Product Simulator) software produces
                                     simulated imaging data for complex wide-area astronomical scenes
                                     based on user inputs, instrument models, and library catalogs for a
                                     range of stellar and/or galactic populations. This page provides the
                                     functionality to run simulations for the WFIRST Wide Field Imager.
                                     Please refer to <a href="http://www.stsci.edu/wfirst/software/STIPS">
                                     The STIPS WFIRST Introductory Page</a> for a detailed introduction and 
                                     description of the tool.""",
                        'JWST': """The STIPS (Space Telescope Image Product Simulator) software produces
                                   simulated imaging data for complex wide-area astronomical scenes
                                   based on user inputs, instrument models, and library catalogs for a
                                   range of stellar and/or galactic populations. This page provides the
                                   functionality to run simulations for the JWST NIRCam and MIRI Imagers.
                                   The STIPS JWST Introductory Page</a> for a detailed introduction and 
                                   description of the tool.""",

#                                   Please refer to <a href="http://www.stsci.edu/wfirst/software/STIPS">
                        
                        'JWST-WFIRST': """The STIPS (Space Telescope Image Product Simulator) software produces
                                          simulated imaging data for complex wide-area astronomical scenes
                                          based on user inputs, instrument models, and library catalogs for a
                                          range of stellar and/or galactic populations. This page provides the
                                          functionality to run simulations for the WFIRST Wide Field Imager,
                                          and the JWST NIRCam and MIRI Imagers. Please refer to 
                                          <a href="http://www.stsci.edu/wfirst/software/STIPS">The STIPS WFIRST 
                                          Introductory Page</a> for a detailed introduction and description of 
                                          the tool."""
                    }

# Introductory HTML
instrument_help_template =  {
                        'WFIRST': """Please contact the <a href="mailto:help@stsci.edu">STScI Helpdesk</a> for assistance.""",
                        'JWST': """Please visit the <a href="http://jwsthelp.stsci.edu/">JWST Helpdesk</a> for assistance.""",
                        'JWST-WFIRST': """Please E-mail <a href="mailto:york@stsci.edu">Brian York</a> for assistance."""
                    }
