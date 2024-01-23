$(function() {
    var $menu = $("#context-menu");

    $menu.menu({
        select: function(event, ui) {
            var $selectedItem = $(ui.item);
            $nestedMenu = $selectedItem.find("ul");

            if ($nestedMenu.length) return; // skip if nested menu exists
            
            var root = $selectedItem.attr('id');

            $.get({
                url: '/get_menu',
		data: {root: root},
                success: function(data){
		    $selectedItem.append(data);

                    // Refresh menu to incorporate newly added items
                    $menu.menu("refresh");
                }
            });
        }
    });
});
