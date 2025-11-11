
$(document).on('click', '[data-toggle="lightbox"]', function(event) {
    event.preventDefault();
    $(this).ekkoLightbox();
});

function showContent(obj){
	$(obj).prev('div').slideDown();
	$(obj).hide();
	$(obj).next('a.less').show();
}
function hideContent(obj){
	$(obj).prev('a.more').show();
	$(obj).prev('a.more').prev('div').slideUp();
	$(obj).hide();
}

$(function(){


	$(".fancybox").fancybox();
	
	$(".modal-transparent").on('show.bs.modal', function () {
	  setTimeout( function() {
	    $(".modal-backdrop").addClass("modal-backdrop-transparent");
	  }, 0);
	});
	
	$(".modal-transparent").on('hidden.bs.modal', function () {
	  $(".modal-backdrop").addClass("modal-backdrop-transparent");
	});
	
	$(".modal-fullscreen").on('show.bs.modal', function () {
	  setTimeout( function() {
	    $(".modal-backdrop").addClass("modal-backdrop-fullscreen");
	  }, 0);
	});
	
	$(".modal-fullscreen").on('hidden.bs.modal', function () {
	  $(".modal-backdrop").addClass("modal-backdrop-fullscreen");
	});
	
	$('a.download').attr('download', '');
	
	/*setTimeout( function(){console.log('debug pustych linkï¿½w do wyï¿½ï¿½czenia w: html/js/script2.js'); brakLinku()}, 2000);
	function brakLinku(){
		obj = $('a');
		$.each( obj, function( key, value ) {
			a = $(obj[key]);
			if(a.attr('href')=="" || a.attr('href')=="#"){
				a.attr('href', 'javascript:void(alert("brak linku"))');
				console.log(a.html().trim()+' - brak linku');
			}
		});
	}*/
	
	

	$('.table-hover td').hover(function(){
		var col = $(this).parent().children().index($(this));
		$('.table-hover td').each(function(index){
			var col2 = $(this).parent().children().index($(this));  
			if (col2==col){
				$(this).addClass('td-hover');
			}            
		}); 
		/*$('.table-hover th').each(function(index){
			var col2 = $(this).parent().children().index($(this));
			if (col2==col){
				if(!$(this).attr('colspan')){
					$(this).addClass('td-hover');
				}
			}            
		});  */

    },
    function(){        
        $('.table-hover td').removeClass('td-hover'); 
        $('.table-hover th').removeClass('td-hover');  
        
    });
	
	/*$marketCalendarEventTabs = $("#market-calendar-event-tabs").tabs({
		cache: true,
		idPrefix: 'market-calendar-event-tab-',
		ajaxOptions: {
			dataType: 'xml'
		},
		select: function(event, ui){ 
			document.location.hash=$(ui.tab).attr("hash");
		}
	}).tabs('scrollable');*/
    
    
    $(".anchorSubmitForm").click(function(){
            $(this).parents('form:first').submit();
            return false;
        });
        $(".captchaRefreshAnchor").bind("click", function() {
		var id = $(this).attr('id');
		id = id.replace('captcha_refresh_anchor_', '');
		
		var imgId = "captcha_img_" + id;
		var imgBasePath = $("#" + imgId).attr('src').substr(0, $("#" + imgId).attr('src').length - 36);
		
		$.post(AJAX_BASE_URL + 'ajaxindex.php?action=GPWCaptcha&start=refreshImage', function(xml) {
				var newId = $( "response", xml ).find('captcha_id').text();
				$("#" + imgId).attr('src', imgBasePath + newId + '.jpg');
				$("#" + imgId).attr('id', 'captcha_img_' + newId);
				$("#captcha_id_" + id).val(newId);
				$("#captcha_id_" + id).attr('id', "captcha_id_" + newId);
				$("#captcha_refresh_anchor_" + id).attr('id', "captcha_refresh_anchor_" + newId);
		}, 'xml');
	});
        $(".anchorClearForm").bind("click", function(){
	    $form = $(this).closest("form");
	    $(':input', $form).each(function() {
	        var type = this.type;
	        var tag = this.tagName.toLowerCase();
	
	        if (type == 'text' || type == 'password' || type == 'email' || tag == 'textarea')
	
	            this.value = "";
	        else if (type == 'checkbox' || type == 'radio')
	            this.checked = false;
	
	        else if (tag == 'select')
	            this.selectedIndex = -1;
	    });
	    return false;
    }); 
	
});

