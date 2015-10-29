$("#container").css({
    "width": $("body").css("width"),
    "height": $("body").css("height")
});

zoomScale = 1;
launchOffset = 0;

if (sjs.current.zoom) zoomScale = parseFloat(sjs.current.zoom);
else zoomScale = 1;


resizeZoomContainer();



function resizeZoomContainer() {
				
    //set values to resize zoom container -- negative margins keep the container centered on the page
    var bodyWidth = parseFloat($("body").css("width")) / zoomScale;
    var bodyHeight = parseFloat($("body").css("height")) / zoomScale;
    var bodyMarginLeft = Math.abs(parseFloat($("body").css("width")) - bodyWidth) / 2;
    var bodyMarginTop = Math.abs(parseFloat($("body").css("height")) - bodyHeight) / 2;
    
    if (zoomScale < 1) {
        bodyMarginTop  = -bodyMarginTop;
        bodyMarginLeft = -bodyMarginLeft;
    }
    
    if (zoomScale > 1) {
    	marginOffset = 0
    }
    
    else {
        marginOffset = parseFloat($("header").css("height"));
	}
    
    $("#container").css({
        '-webkit-transform': 'scale(' + zoomScale + ')',
        '-moz-transform': 'scale(' + zoomScale + ')',
        '-ms-transform': 'scale(' + zoomScale + ')',
        '-o-transform': 'scale(' + zoomScale + ')',
        'transform': 'scale(' + zoomScale + ')',
        "width": bodyWidth + "px",
        "height": bodyHeight + "px",
        "margin-left": bodyMarginLeft + "px",
        "margin-top": bodyMarginTop + "px"
    });


}

$("#zoomOut").click(function() {
    zoomScale = parseFloat(zoomScale) - .1;
    if (zoomScale < .1) zoomScale = .1;

    resizeZoomContainer();
    updateSheet();

});


$("#zoomIn").click(function() {
    zoomScale = parseFloat(zoomScale) + .1;
    if (zoomScale > 4) zoomScale = 4;

    resizeZoomContainer();
    updateSheet();

});


//set sources to be draggable & resizable
$(".sheetItem").resizable({

    stack: ".source",
    handles: "nw, ne, se, sw",
    stack: ".source",

    start: function(event, ui) {
		  console.log("left : " + $(this).css("left")+ ' '+ ui.position.left);
		  console.log("top : " + $(this).css("top")+ ' '+ui.position.top);
		  
		  
        ui.position.left = ui.position.left/ zoomScale;
        ui.position.top = ui.position.top/ zoomScale - marginOffset;


    },

    resize: function(event, ui) {

        var changeWidth = ui.size.width - ui.originalSize.width; // find change in width
        var newWidth = ui.originalSize.width + changeWidth / zoomScale; // adjust new width by our zoomScale

        var changeHeight = ui.size.height - ui.originalSize.height; // find change in height
        var newHeight = ui.originalSize.height + changeHeight / zoomScale; // adjust new height by our zoomScale

        ui.size.width = newWidth;
        ui.size.height = newHeight;

    },

    stop: function() {
        updateSheet();
    }



}).draggable({
    stack: ".sheetItem",
    start: function(event, ui) {
        ui.position.left = 0;
        ui.position.top = 0;
    },
    drag: function(event, ui) {

        var changeLeft = ui.position.left - ui.originalPosition.left; // find change in left
        var newLeft = ui.originalPosition.left + changeLeft / ((zoomScale)); // adjust new left by our zoomScale

        var changeTop = ui.position.top - ui.originalPosition.top - marginOffset; // find change in top
        var newTop = ui.originalPosition.top + changeTop / zoomScale; // adjust new top by our zoomScale

        ui.position.left = newLeft;
        ui.position.top = newTop;
        

    },
    stop: function() {
        updateSheet();
    }
}).each(function(index) {

launchOffset = launchOffset + 75;

    if (sjs.current.visualNodes) {
        $(this).animate({

            "left": sjs.current.visualNodes[index].x + "px",
            "top": sjs.current.visualNodes[index].y + "px",
            "width": sjs.current.visualNodes[index].width + "px",
            "height": sjs.current.visualNodes[index].length + "px",
            "z-index": sjs.current.visualNodes[index].zindex
        }).addClass(sjs.current.visualNodes[index].bgColor);
    }

	else {

        $(this).animate({

            "left": launchOffset + "px",
            "top": launchOffset + "px",
            "z-index":index
		});
	}

if ($(this).hasClass("english")) {$(this).find(".he").hide() }
else if ($(this).hasClass("hebrew")) {$(this).find(".en").hide() }

}).prepend('<div class="colorSelect"><div class="pink"></div><div class="white"></div><div class="yellow"></div><div class="green"></div><div class="blue"></div></div>').hover(
    function() {
        $(this).find(".colorSelect").first().css("visibility", "visible");
    },
    function() {
        $(this).find(".colorSelect").first().css("visibility", "hidden");
    }

);

$(".colorSelect div").click( function() {

	$(this).closest(".sheetItem").removeClass( "yellow pink blue green white" ).addClass( $(this).attr('class') );
	
	updateSheet();


});


saveFlashShown = 0;

function updateSheet() {

	if (!sjs._uid && saveFlashShown == 0) {
		sjs.alert.flash("You need to login to save edits");
		saveFlashShown = 1;
	}

	else if (!sjs.can_edit && saveFlashShown == 0) {
	 	sjs.alert.flash("You don't have permission to save edits");
		saveFlashShown = 1;
	}


    else if (sjs._uid && sjs.can_edit) {

        toJson = '[';

        $(".sheetItem").each(function() {

            var x = (parseFloat($(this).css('left')));
            var y = (parseFloat($(this).css('top')));
            var width = $(this).width();
            var length = $(this).height();
            var zindex = $(this).css('z-index');
            if (zindex == "auto") zindex = 0;
            
            
            bgColor = "white";
            if ($(this).hasClass("yellow")) bgColor = "yellow";
            if ($(this).hasClass("pink")) bgColor = "pink";
            if ($(this).hasClass("blue")) bgColor = "blue";
            if ($(this).hasClass("green")) bgColor = "green";
            
            
            toJson = toJson + '{ "x" : ' + x + ', "y" : ' + y + ', "width" : ' + width + ', "length" : ' + length + ', "zindex" : ' + zindex + ', "bgColor" : "'+ bgColor +'"},';

        });

        toJson = toJson.slice(0, -1) + ']';

        $.post("/api/sheets/" + sjs.current.id + "/visualize", {
                visualNodes: toJson,
                zoom: zoomScale
            },

            function(data) {
                if ("error" in data) {
                    sjs.alert.message(data.error);
                } else {
                    //	sjs.alert.flash("Sheet updated.");
                }
            }

        );
    }
    
}

$("#saveButton").click(function() {
    updateSheet();
});