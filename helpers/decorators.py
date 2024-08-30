import os
import logging
import functools
import time

def rate_limiter(sleep_time):
    def decorator_rate_limiter(func):
      @functools.wraps(func)
      def wrapper(*args, **kwargs):
          time.sleep(sleep_time)

          start_time = time.perf_counter()
          value = func(*args, **kwargs)
          end_time = time.perf_counter()
          run_time = end_time - start_time
          logging.info(f"Finished {func.__name__}() in {run_time:.4f} secs")

          return value
      return wrapper
    
    return decorator_rate_limiter

def timer_decorator(func):
    def wrapper_function(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        run_time = time.perf_counter() - start_time
        logging.info(f"Finished {func.__name__}() in {run_time:.4f} secs")
        return result

    return wrapper_function

def async_timer_decorator(func):
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = await func(*args, **kwargs)
        run_time = time.perf_counter() - start_time
        logging.info(f"Finished {func.__name__}() in {run_time:.4f} secs")
        return result
    
    return wrapper
   