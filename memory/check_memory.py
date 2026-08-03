from . import default, integration_short_term

user_id = "jar"

print(integration_short_term.build_memory_block(default.create_long_term(), user_id=user_id,
                                                input_text="Hello.",
                                                past_messages=[]))
