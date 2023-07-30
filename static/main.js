function addToResponse(text, temp, temprend) {
   	const atBottom = isAtBottom();
    temp.innerHTML += htmlEscape(text);
	temprend.innerHTML = md.render(htmlDecode(temp.innerHTML));
	if (atBottom)
		scrollToBottom();
}

function endResponse(temp, temprend) {
    temp.removeAttribute('id');
    temprend.removeAttribute('id');
}
