// Function to handle up/down-vote and make AJAX call
function voteUp() {
    $(this).effect('shake', {distance: 5}, 300);
    
    const responseId = $(this).data("link-id");

    $.ajax({
        url: "/api/responses/" + encodeURIComponent(responseId) + "/vote",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ value: "up" })
    });
}

function voteDown() {
    $(this).effect('shake', {distance: 5}, 300);

    const responseId = $(this).data("link-id");

    $.ajax({
        url: "/api/responses/" + encodeURIComponent(responseId) + "/vote",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ value: "down" })
    });
}
