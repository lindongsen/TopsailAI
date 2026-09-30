"""Import fixture that never completes without supervisor termination."""

import time

while True:
    time.sleep(1)
