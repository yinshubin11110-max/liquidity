// JavaScript Document


	// JavaScript Document
	
	 var isMobile = {
		Android: function() {
			return /Android/i.test(navigator.userAgent);
		},
		BlackBerry: function() {
			return /BlackBerry/i.test(navigator.userAgent);
		},
		iOS: function() {
			return /iPhone|iPad|iPod/i.test(navigator.userAgent);
		},
		Opera: function() {
			return /Opera Mini/i.test(navigator.userAgent);
		},
		Windows: function() {
			return /IEMobile/i.test(navigator.userAgent);
		},
		loyoutWidth: function() {
			
			if($( window ).width() < 992) {
				return true;
			}				

		},
		any: function() {
			return (isMobile.Android() || isMobile.BlackBerry() || isMobile.iOS() || isMobile.Opera() || isMobile.Windows() || isMobile.loyoutWidth());
		}
	};
	
	// global varibles
	
	
	// data prototypes for bootstrap-datapicker
	/*Date.prototype.monthNames = ["Sty.","Lut.","Mar.","Kwi.","Maj","Cze.","Lip.","Sie.","Wrz.","PaÅº.","Lis.","Gru."];
	Date.prototype.dayNames = ["Ndz.","Pn.","Wt.","År.","Czw.","Pt.","Sob."];											
	Date.prototype.getMonthName = function() {return this.monthNames[this.getMonth()];};
	Date.prototype.getDayName = function() {return this.dayNames[this.getDay()];};*/
	
	
	
if (navigator.appVersion.indexOf("MSIE 10") !== -1)
	{
		ie = '10'
	}
	var UAString = navigator.userAgent;
	if (UAString.indexOf("Trident") !== -1 && UAString.indexOf("rv:11") !== -1)
	{
		ie = '11'
	}
	
	
	function onDOMReadyInit() {
		
		
		$('[data-toggle="subMenu"]').each(function(index, element) {
			$this = $(this);
			$thisID = $this.attr('id');
						
			$this.click(function(e) {
	            e.preventDefault();
				$('[subMenu-labelledby]').each(function(index, element) {
					if( $(this).is(':visible')) {
						 $(this).slideUp('fast');
					}                   
                });	
							
				thisID = $(this).attr('id');
				
				if( $('[subMenu-labelledby="' + thisID + '"]').is(':hidden') ) {
					$('[subMenu-labelledby="' + thisID + '"]').slideDown('fast');	
				}

            });
			
        });
		
			
		toggleCheckbox();

		if(isMobile.any()) {			
			$('.customselect').show();
			disableHover();
		}
		else {
			$('.customselect').customSelect();
		}
		
		// prevent dropdonw from closing when clicked
		$('.dropdown-menu input, .dropdown-menu label').click(function(e) {
			e.stopPropagation();
		});
		
		// responsive tabs
		fakewaffle.responsiveTabs(['xs']);
		
		// autocollapse tabs
		autocollapse(); // when document first loads
		//$(window).on('resize', autocollapse); // when window is resized
		
		var t = null;

		$(window).on('resize',
		function() {
		   if (t!= null) clearTimeout(t);		
		   t = setTimeout( function() { autocollapse() }, 1000);
		});
		
		
						
		if (typeof ie == 'undefined') {ie = null}

		if(ie == '8') {	
		
			// :after filter patch	
			$('[data-after]').each(function(index, element) {
				if( !$('.after', element).length ) {
                	$(element).prepend('<span class="after"></span>');
				}
            });
			// :before filter patch	
			$('[data-before]').each(function(index, element) {
                if( !$('.before', element).length ) {
					$(element).prepend('<span class="before"></span>');
				}
            });
			
			
			// flex childs height patch      
				
			function flexPatchIE8() {				
				$('.flex.flexWrap').each(function(index, element) { //  find every flex.flexWrap element
					$('> *:not(.clearfix)', element).css('height','' ); // remove height from every child				
				});					
				
				if( !$('.ie_respond_feedback').is(':visible') ) { // if respond.js finished
						
					$('.flex.flexWrap').each(function(index, element) { //  find every flex.flexWrap element						
						if ($(element).find('> *').length > 1) { // if has more then one child
							$('> *:not(.clearfix)', element).addClass('margin-bottom-0');
							$('> *:not(.clearfix)', element).css('height',$(element).height() ); // add equal height to every child
							$('> *:not(.clearfix)', element).removeClass('margin-bottom-0');
						}					
					});	

				}	
			}
			
			var respondInit =  setTimeout(flexPatchIE8, 1000);
			
			window.onresize = function(event) {
				flexPatchIE8()
			};

		} //if(ie == '8')
		
		else if(ie == '9') {	
		
			// flex childs height patch      	
			function flexPatchIE9() {					
				$('.flex.flexWrap').each(function(index, element) { //  find every flex.flexWrap element
					$('> *:not(.clearfix)', element).css('height','' ); // remove height from every child				
				});					
					
				$('.flex.flexWrap').each(function(index, element) { //  find every flex.flexWrap element						
					if ($(element).find('> *').length > 1) { // if has more then one child																			
						$(element).removeClass('flex');
						$('> *:not(.clearfix)', element).addClass('margin-bottom-0');
						$('> *:not(.clearfix)', element).css('height',$(element).height() ); // add equal height to every child
						$(element).addClass('flex');
						$('> *:not(.clearfix)', element).removeClass('margin-bottom-0');
					}					
				});	
	
			};	
			
			flexPatchIE9();	
			
			window.onresize = function(event) {
				flexPatchIE9()
			};

		} //if(ie == '9')

		
		
		if(ie == '10' || ie == '11') {
			
			$('.fancyOrderedList .item-header .item-count').each(function(index, element) {
				$(this).css('height', $(this).parent().height())
			});
		
		}
		
		
		
	};
	
	
	
	function toggleCheckbox() {
		
		$this = $('[data-select-all]')
		
		$this.each(function(index, element) {
			
			$(element).click(function(event) {
				if(this.checked) {
					$(element).parent().next().find(':checkbox').each(function() {
						this.checked = true;
					});
				}
				else {
					$(element).parent().next().find(':checkbox').each(function() {
						this.checked = false;
					});
				}
			}); 
			           
        });
		

		
		
	}
	
	
	$(document).ready(function(e) {
        
		onDOMReadyInit()
		
    });
	
	
	
	
	var autocollapse = function() {
	  
	  
	  $('.nav-tabs.autocollapse').each(function(index, element) {

		  var tabs = $(element);
		  var tabsHeight = tabs.innerHeight();
		  
		  if(!$('.lastTab', tabs).length) {			  
			  
			tabs.append('<li class="lastTab" />')
			$(".lastTab", tabs).hide().append('<a class="nav-link dropdown-toggle" data-toggle="dropdown" data-after="true" data-before="true" href="javascript:void(0)"/>');
			$(".lastTab .nav-link", tabs).append('<i class="icon-arrow-down"/>').after('<ul class="dropdown-menu dropdown-menu-right"/>');

		  }

	  
		  if (tabsHeight >= 50) {			  
	 
			while(tabsHeight > 50) {
				var children = tabs.children('li:not(:last-child)');				
				var count = children.length;				
				$('.lastTab', tabs).show();		
				$('.dropdown-menu', tabs).prepend(children[count-1]);				
				tabsHeight = tabs.innerHeight();
			}
	
		  }
	  
		  else {

			while(tabsHeight < 50 && ($('.dropdown-menu li', tabs).length>0)) {
			  var collapsed = $('.dropdown-menu', tabs).children('li');
			  var count = collapsed.length;
			  $(collapsed[0]).insertBefore(tabs.children('li:last-child'));
			  tabsHeight = tabs.innerHeight();
			}
			
			if($('.dropdown-menu li', tabs).length == 0) {$('.lastTab', tabs).hide(); }
			
			if (tabsHeight>=50) { // double chk height again
				autocollapse();
			}
			
		  }
  
		  
		/*$('.autocollapse .nav-item').click( function() {
			  
			  var activeItem = $(this).closest('.autocollapse').find('.nav-item.active');
			  activeItem.removeClass('active');
			  $(this).addClass('active');
			  
		})*/
		
		  

    });
	};

	// bootstrap breakpoint JS callback 
		
	(function($, document, window, viewport){
	
		var colspan = function() {
			
			$('.table th, .table td').each(function(index, element) {
                
				$cell = $(element);		
				if($cell.attr('data-colspan-lg') && viewport.is("lg") ) {
					$cell.attr('colspan', '' );
					$cell.attr('colspan', $cell.attr('data-colspan-lg') )
				}
				if($cell.attr('data-colspan-md') && viewport.is("md")) {
					$cell.attr('colspan', '' );
					$cell.attr('colspan', $cell.attr('data-colspan-md') )
				}
				if($cell.attr('data-colspan-sm') && viewport.is("sm")) {
					$cell.attr('colspan', '' );
					$cell.attr('colspan', $cell.attr('data-colspan-sm') )
				}
				if($cell.attr('data-colspan-xs') && viewport.is("xs")) {
					$cell.attr('colspan', '' );
					$cell.attr('colspan', $cell.attr('data-colspan-xs') )
				}				
				
            });	
			
			$('colgroup col').each(function(index, element) {
                
				$cell = $(element);		
				if($cell.attr('data-span-lg') && viewport.is("lg") ) {
					$cell.attr('span', '' );
					$cell.attr('span', $cell.attr('data-span-lg') )
				}
				if($cell.attr('data-span-md') && viewport.is("md")) {
					$cell.attr('span', '' );
					$cell.attr('span', $cell.attr('data-span-md') )
				}
				if($cell.attr('data-span-sm') && viewport.is("sm")) {
					$cell.attr('span', '' );
					$cell.attr('span', $cell.attr('data-span-sm') )
				}
				if($cell.attr('data-span-xs') && viewport.is("xs")) {
					$cell.attr('span', '' );
					$cell.attr('span', $cell.attr('data-span-xs') )
				}				
				
            });	
			
			
					

		};
	
		// Executes once whole document has been loaded
		$(document).ready(function() {
			colspan();
			//console.log('Current breakpoint:', viewport.current());
	
		});
	
		$(window).resize(
			viewport.changed(function(){
				colspan();
				//console.log('Current breakpoint:', viewport.current());
			})
		);
	
	})(jQuery, document, window, ResponsiveBootstrapToolkit);

	function createCookie( name, value, days ) {
		if( days ) {
			var date = new Date();
			date.setTime( date.getTime() + ( days * 24 * 60 * 60 * 1000 ) );
			var expires = "; expires=" + date.toGMTString();
		}
		else
			var expires = "";
		document.cookie = name + "=" + value + expires + "; path=/; secure;";
	}
	function readCookie( name ) {
		var nameEQ = name + "=";
		var ca = document.cookie.split(';');
		for( var i=0; i < ca.length; i++ ) {
			var c = ca[i];
			while( c.charAt(0) == ' ' ) {
				c = c.substring( 1, c.length );
			}
			if( c.indexOf( nameEQ ) == 0 ) {
				return c.substring( nameEQ.length, c.length );
			}
		}
		return null;
	}
	function eraseCookie( name ) {
		createCookie( name, "", -1 );
	}
