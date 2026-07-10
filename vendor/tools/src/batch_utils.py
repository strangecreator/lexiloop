import time
import json
import pathlib
import typing as tp

# aiohttp & related imports
import asyncio
import aiohttp

# local imports
from . import utils
from . import exceptions


__all__ = [
    "run_batch_aiohttp",
]


# async def run_batch_aiohttp(
#     run_single_func: tp.Callable,
#     args_list: list[dict[str, tp.Any]],
#     batch_size: int = 100,
#     timeout: int = 240,
#     save_to_file: str | None = None,
#     override: bool = False,
#     only_new: bool = True,
#     simultaneous_connections_per_task: int = 1,

#     # additional
#     verbose: bool = True,
#     traceback_verbose: bool = False,
#     verbose_prefix: str = '',
#     skip_on_none: bool = False,
#     skip_on_error: bool = False,
#     tls_dns_cache: int = 300,
#     session_timeout: float = 31 * 60,

#     # other
#     **kwargs,
# ) -> dict:
#     if not args_list:
#         return {
#             "count": 0,
#             "elapsed_time": 0.0,
#             "results": [],
#             "indices": [],
#         }

#     concurrency = max(1, min(batch_size, len(args_list)))
#     connector = aiohttp.TCPConnector(
#         limit=concurrency * simultaneous_connections_per_task,
#         limit_per_host=concurrency * simultaneous_connections_per_task,
#         ttl_dns_cache=tls_dns_cache,
#         enable_cleanup_closed=True,
#     )

#     session_timeout = aiohttp.ClientTimeout(total=session_timeout)
#     semaphore = asyncio.Semaphore(concurrency)

#     file_handle = None
#     processed_indices: set[int] = set()

#     if save_to_file is not None:
#         path = pathlib.Path(save_to_file)
#         path.parent.mkdir(parents=True, exist_ok=True)

#         if path.exists() and path.is_file():
#             # maybe some data inside, checking
#             if path.stat().st_size > 0:
#                 if not override:
#                     raise FileExistsError(
#                         f"Refusing to overwrite non-empty file: '{path}'. "
#                         "Pass override=True to clear it or append to it (depending on the `only_new` argument)."
#                     )

#                 if override and only_new:
#                     try:
#                         with open(path, 'r', encoding="utf-8") as reader:
#                             for line in reader:
#                                 line = line.strip()
#                                 if not line:
#                                     continue

#                                 try:
#                                     data = json.loads(line)
#                                 except Exception:
#                                     continue

#                                 index = data.get("index")
#                                 if isinstance(index, int):
#                                     processed_indices.add(index)
#                     except FileNotFoundError:
#                         processed_indices = set()

#         file_mode = 'a' if (override and only_new) else 'w'
#         file_handle = open(path, file_mode, encoding="utf-8")

#     async def bounded_eval(index: int, args: dict) -> tuple[int, dict | None, BaseException | None]:
#         await semaphore.acquire()
#         try:
#             try:
#                 result = await run_single_func(
#                     **utils.extend_dict(
#                         utils.extend_dict(args, {"timeout": timeout}, override=False, inplace=False),
#                         kwargs, override=False, inplace=False,
#                     ),
#                     session=session,
#                 )
#                 return index, result, None
#             except BaseException as e:
#                 return index, None, e
#         finally:
#             semaphore.release()

#     start_time = time.perf_counter()

#     try:
#         async with aiohttp.ClientSession(connector=connector, timeout=session_timeout) as session:
#             instances_to_process = [
#                 (index, args)
#                 for index, args in enumerate(args_list)
#                 if not (override and only_new and index in processed_indices)
#             ]

#             tasks = [
#                 asyncio.create_task(bounded_eval(index, args))
#                 for (index, args) in instances_to_process
#             ]

#             results_ordered: list[dict | None] = [None] * len(args_list)

#             for future in asyncio.as_completed(tasks):
#                 index, result, error = await future

#                 if error is not None:
#                     if isinstance(error, exceptions.NoneError) and skip_on_none:
#                         if verbose:
#                             print(verbose_prefix, f"The result of run with index={index} is None (NoneError). Skipped.", sep='')

#                         continue

#                     if skip_on_error:
#                         if verbose:
#                             print(verbose_prefix, (
#                                 f"Error in run with index={index}: "
#                                 f"[{utils.exception_to_string(error, traceback_verbose=traceback_verbose)}]. Skipped."
#                             ), sep='')
                        
#                         continue

#                     raise error

#                 if verbose:
#                     price_string = ''

#                     if isinstance(result, dict) and "total_price" in result and isinstance(result["total_price"], (int, float)):
#                         price_string = f" Total price: {result['total_price']}."

#                     print(verbose_prefix, f"Task with index={index} has been completed.{price_string}", sep='')

#                 results_ordered[index] = result

#                 if file_handle is not None:
#                     file_handle.write(json.dumps({"index": index, **result}, ensure_ascii=False) + "\n")
#                     file_handle.flush()

#     finally:
#         if file_handle is not None:
#             file_handle.close()

#     elapsed_time = time.perf_counter() - start_time

#     results, indices = [], []

#     for i in range(len(results_ordered)):
#         if results_ordered[i] is not None:
#             results.append(results_ordered[i])
#             indices.append(i)

#     return {
#         "elapsed_time": elapsed_time,
#         "count": len(results),
#         "results": results,
#         "indices": indices,
#     }


# ----------------------------------- The scheduler should not create all tasks up front.


async def run_batch_aiohttp(
    run_single_func: tp.Callable,
    args_list: list[dict[str, tp.Any]],
    batch_size: int = 100,
    timeout: int = 240,
    save_to_file: str | None = None,
    override: bool = False,
    only_new: bool = True,
    simultaneous_connections_per_task: int = 1,

    # additional
    verbose: bool = True,
    traceback_verbose: bool = False,
    verbose_prefix: str = '',
    skip_on_none: bool = False,
    skip_on_error: bool = False,
    save_errors_to_file: bool = False,
    tls_dns_cache: int = 300,
    session_timeout: float = 31 * 60,

    # other
    **kwargs,
) -> dict:
    if not args_list:
        return {
            "count": 0,
            "elapsed_time": 0.0,
            "results": [],
            "indices": [],
        }

    concurrency = max(1, min(batch_size, len(args_list)))
    connector = aiohttp.TCPConnector(
        limit=concurrency * simultaneous_connections_per_task,
        limit_per_host=concurrency * simultaneous_connections_per_task,
        ttl_dns_cache=tls_dns_cache,
        enable_cleanup_closed=True,
    )

    session_timeout = aiohttp.ClientTimeout(total=session_timeout)

    file_handle = None
    processed_indices: set[int] = set()

    if save_to_file is not None:
        path = pathlib.Path(save_to_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and path.is_file():
            # maybe some data inside, checking
            if path.stat().st_size > 0:
                if not override:
                    raise FileExistsError(
                        f"Refusing to overwrite non-empty file: '{path}'. "
                        "Pass override=True to clear it or append to it (depending on the `only_new` argument)."
                    )

                if override and only_new:
                    try:
                        with open(path, 'r', encoding="utf-8") as reader:
                            for line in reader:
                                line = line.strip()
                                if not line:
                                    continue

                                try:
                                    data = json.loads(line)
                                except Exception:
                                    continue

                                index = data.get("index")
                                if isinstance(index, int) and "__error__" not in data:
                                    processed_indices.add(index)
                    except FileNotFoundError:
                        processed_indices = set()

        file_mode = 'a' if (override and only_new) else 'w'
        file_handle = open(path, file_mode, encoding="utf-8")

    async def run_one(
        index: int,
        args: dict,
        session: aiohttp.ClientSession,
    ) -> tuple[int, dict | None, BaseException | None]:
        try:
            result = await run_single_func(
                **utils.extend_dict(
                    utils.extend_dict(args, {"timeout": timeout}, override=False, inplace=False),
                    kwargs, override=False, inplace=False,
                ),
                session=session,
            )
            return index, result, None
        except BaseException as e:
            return index, None, e

    start_time = time.perf_counter()

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=session_timeout) as session:
            instances_to_process = [
                (index, args)
                for index, args in enumerate(args_list)
                if not (override and only_new and index in processed_indices)
            ]

            results_ordered: list[dict | None] = [None] * len(args_list)

            pending: dict[asyncio.Task, tuple[int, dict[str, tp.Any]]] = {}
            next_pos = 0

            def start_next_tasks() -> None:
                nonlocal next_pos

                while len(pending) < concurrency and next_pos < len(instances_to_process):
                    index, args = instances_to_process[next_pos]
                    next_pos += 1

                    task = asyncio.create_task(run_one(index, args, session))
                    pending[task] = (index, args)

            start_next_tasks()

            while pending:
                done, _ = await asyncio.wait(
                    list(pending.keys()),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                completed: list[tuple[int, dict | None, BaseException | None]] = []

                for task in done:
                    index, _args = pending.pop(task)

                    try:
                        completed.append(task.result())
                    except BaseException as e:
                        # this should normally not happen because run_one already catches BaseException,
                        # but keeping this fallback makes the scheduler safer
                        completed.append((index, None, e))

                # asyncio.wait() returns a set, so equal-speed tasks otherwise
                # produce nondeterministic JSONL ordering. Preserve source order
                # within each completion wave while still saving results eagerly.
                completed.sort(key=lambda item: item[0])

                fatal_error: BaseException | None = None

                for index, result, error in completed:
                    if error is not None:
                        if isinstance(error, exceptions.NoneError) and skip_on_none:
                            if verbose:
                                print(verbose_prefix, f"The result of run with index={index} is None (NoneError). Skipped.", sep='')

                            continue

                        if skip_on_error:
                            error_text = utils.exception_to_string(error, traceback_verbose=traceback_verbose)
                            if verbose:
                                print(verbose_prefix, (
                                    f"Error in run with index={index}: [{error_text}]. Skipped."
                                ), sep='')
                            if file_handle is not None and save_errors_to_file:
                                file_handle.write(json.dumps({
                                    "index": index,
                                    "__error__": str(error),
                                    "__error_type__": type(error).__name__,
                                    "__traceback__": error_text,
                                }, ensure_ascii=False) + "\n")
                                file_handle.flush()
                            continue

                        if fatal_error is None:
                            fatal_error = error

                        continue

                    if verbose:
                        price_string = ''

                        if isinstance(result, dict) and "total_price" in result and isinstance(result["total_price"], (int, float)):
                            price_string = f" Total price: {result['total_price']}."

                        print(verbose_prefix, f"Task with index={index} has been completed.{price_string}", sep='')

                    results_ordered[index] = result

                    if file_handle is not None:
                        file_handle.write(json.dumps({"index": index, **result}, ensure_ascii=False) + "\n")
                        file_handle.flush()

                if fatal_error is not None:
                    remaining_tasks = list(pending.keys())

                    for task in remaining_tasks:
                        task.cancel()

                    if remaining_tasks:
                        await asyncio.gather(*remaining_tasks, return_exceptions=True)

                    raise fatal_error

                start_next_tasks()

    finally:
        if file_handle is not None:
            file_handle.close()

    elapsed_time = time.perf_counter() - start_time

    results, indices = [], []

    for i in range(len(results_ordered)):
        if results_ordered[i] is not None:
            results.append(results_ordered[i])
            indices.append(i)

    return {
        "elapsed_time": elapsed_time,
        "count": len(results),
        "results": results,
        "indices": indices,
    }