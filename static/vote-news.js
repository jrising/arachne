// Function to handle up/down-vote and make AJAX call
function voteUp() {
    $(this).effect('shake', {distance: 5}, 300);
    var linkId = $(this).closest('.vote-icons').data('link-id');
    let upperdiv = document.getElementById('pastmessages');
    $.get({
        url: '/vote-updown',
	data: { id: linkId, prob: 1, past_messages: document.getElementById('pastmessages').innerHTML },
	function (data) {
            // Handle successful up-vote
            console.log('Up-vote successful for link ID:', linkId);
        }}).fail(function() {
            // Handle errors
            console.error('Error occurred.');
        });
}

function voteDown() {
    $(this).effect('shake', {distance: 5}, 300);
    var linkId = $(this).closest('.vote-icons').data('link-id');
    let upperdiv = document.getElementById('pastmessages');
    $.get({
        url: '/vote-updown',
	data: { id: linkId, prob: 0, past_messages: document.getElementById('pastmessages').innerHTML },
	function (data) {
            // Handle successful up-vote
            console.log('Down-vote successful for link ID:', linkId);
        }}).fail(function() {
            // Handle errors
            console.error('Error occurred.');
        });
}
