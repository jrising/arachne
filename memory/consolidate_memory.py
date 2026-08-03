from . import default

ltm = default.create_long_term()

notes = ltm.consolidate_user_memory_incremental("jar", memory_batch_size=40, task_batch_size=15)
for note in notes:
    print(note)
