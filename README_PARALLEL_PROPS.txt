BEATTHEBOOKS PARALLEL PROPS UPDATE
==================================

Files:
- run_big_auto_update_PARALLEL_PROPS.bat
- scripts\Pipeline\run_props_all_parts_parallel.bat
- scripts\Pipeline\run_props_parallel_worker.bat

Behaviour:
- The six bookmaker props parts launch simultaneously.
- Steps inside each bookmaker part remain sequential.
- This preserves scraper -> fix -> merge dependencies.
- The controller waits for all six parts.
- If any part fails, the master stops before validation, page generation or push.
- Per-part logs are written under the Windows TEMP folder and are not added to Git.

Run full master:
    call run_big_auto_update_PARALLEL_PROPS.bat

Run props only:
    call scripts\Pipeline\run_props_all_parts_parallel.bat
