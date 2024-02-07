function addsubmenu($option, afterwards) {
    var root = $option.attr('id');
    return $.get({
        url: '/get_menu',
	data: {root: root},
        success: function(data) {
	    $dom = $(data);
	    if ($dom.length > 0) {
		var wrapped = $('<ul>').html($dom);
		$option.append(wrapped);
	    }
	    afterwards();
        }
    });
}

function addsubmenulist($options, afterwards) {
    $.when.apply($, $options.map(function() {
	return addsubmenu($(this), function() {});
    })).done(function() {
	afterwards();
    });
}

$(function() {
    var $menu = $("#context-menu");

    // Fill in submenus for all entries
    addsubmenulist($menu.children(), function() {
	$menu.menu({
	    classes: { 'ui-menu': 'w200px' },
	    select: function(event, ui) {
		var $selectedItem = $(ui.item);
		$('#menu-option').val($selectedItem.attr('id'));
		$('#menu-display').html($selectedItem.attr('id'));
	    },
            focus: function(event, ui) {
		var $selectedItem = $(ui.item);
		$nestedMenu = $selectedItem.find("ul");
		if ($nestedMenu.length == 0) {
		    if ($selectedItem.hasClass('child-check')) {
			// Case 1: There's no nested list and we've already tried to add one
			return;
		    } else {
			// Case 2: We should try to add the nested list.
			$selectedItem.addClass('child-check');
			addsubmenu($selectedItem, function() {
			    // Refresh menu to incorporate newly added options
			    $menu.menu("refresh");
			});
		    }
		} else {
		    if ($nestedMenu.hasClass('child-check')) {
			// Case 3: There is a nested list we've already added and it's been processed for the next level
			return;
		    } else {
			// Case 4: There is a nested list we've already added and we want to check the next level
			$nestedMenu.addClass('child-check');
			addsubmenulist($nestedMenu.children(), function() {
			    // Refresh menu to incorporate newly added options
			    $menu.menu("refresh");
			});
		    }
		}
	    }
	});
    });
});
