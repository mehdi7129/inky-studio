"""Inert, exact upstream method fixtures, Pimoroni inky v2.5.0.

Tag commit: 29e1af86db54dad8c997db544fc5deb3b047d779
Source: https://github.com/pimoroni/inky/tree/v2.5.0/inky
Tests compile only BUSY/update methods against inert collaborators; GPIO
acquisition/reset/init commands are excluded. No hardware qualification.

MIT License

Copyright (c) 2018 Pimoroni Ltd.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

"""

FILE_SHA256 = {'ac073': '07ef76f3854d279e19cc082b5bc96b8bc20b6aed967747357e5dff4cb9c65324', 'uc8159': 'c597ed914036e8393ad7d04a9731ddc77f1f7ff12851580fef5a8c4f9db1411b', 'e640': 'bc7942ed3791ad4d8087e1d7b6f7085deb7375d31df25c14f026f5dfa6229a1a', 'e673': '7dc4d2236097481dae804bf7defb6900c162d337f8a020e09e5f63a11e700ef0', 'el133uf1': '48ff387e6f9ee7b53c176beb7ca8cd58ea91a7e362e4eda9a75a05eef633374d'}

CONSTANTS = {'ac073': {'AC073TC1_DRF': 18, 'AC073TC1_DTM': 16, 'AC073TC1_POF': 2, 'AC073TC1_PON': 4},
 'e640': {'EL640_BTST2': 6, 'EL640_DRF': 18, 'EL640_DTM1': 16, 'EL640_POF': 2, 'EL640_PON': 4},
 'e673': {'EL673_BTST2': 6,
          'EL673_DRF': 18,
          'EL673_DTM1': 16,
          'EL673_POF': 2,
          'EL673_PON': 4,
          'EL673_PSR': 0},
 'el133uf1': {'CS0_SEL': 1,
              'CS1_SEL': 2,
              'CS_BOTH_SEL': 3,
              'EL133UF1_DRF': 18,
              'EL133UF1_DTM': 16,
              'EL133UF1_POF': 2,
              'EL133UF1_PON': 4},
 'uc8159': {'UC8159_DRF': 18, 'UC8159_DTM1': 16, 'UC8159_POF': 2, 'UC8159_PON': 4}}

BUSY_PINS = {'ac073': 17, 'uc8159': 17, 'e640': 17, 'e673': 17, 'el133uf1': 17}


SOURCES = {
    'ac073': r'''class Inky:
    def _busy_wait(self, timeout=40.0):
        """Wait for busy/wait pin."""
        # If the busy_pin is *high* (pulled up by host)
        # then assume we're not getting a signal from inky
        # and wait the timeout period to be safe.
        if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            warnings.warn(f"Busy Wait: Held high. Waiting for {timeout:0.2f}s", stacklevel=2)
            time.sleep(timeout)
            return

        if gpiodevice.wait_for_edge(self._gpio, self.busy_pin, timeout) is None:
            warnings.warn(f"Busy Wait: Timed out after {timeout:0.2f}s", stacklevel=2)
            return

    def _update(self, buf):
        """Update display.

        Dispatches display update to correct driver.

        :param buf_a: Black/White pixels
        :param buf_b: Yellow/Red pixels

        """

        self.setup()

        # TODO there has to be a better way to force the white colour to be used instead of clear...

        for i in range(len(buf)):
            if buf[i] & 0xF == 7:
                buf[i] = (buf[i] & 0xF0) + 1
                # print buf[i]
            if buf[i] & 0xF0 == 0x70:
                buf[i] = (buf[i] & 0xF) + 0x10
                # print buf[i]

        self._send_command(AC073TC1_DTM, buf)

        self._send_command(AC073TC1_PON)
        self._busy_wait(0.4)

        self._send_command(AC073TC1_DRF, [0x00])
        self._busy_wait(45.0)  # 41 seconds in testing

        self._send_command(AC073TC1_POF, [0x00])
        self._busy_wait(0.4)
''',
    'uc8159': r'''class Inky:
    def _busy_wait(self, timeout=40.0):
        """Wait for busy/wait pin."""
        # If the busy_pin is *high* (pulled up by host)
        # then assume we're not getting a signal from inky
        # and wait the timeout period to be safe.
        if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            warnings.warn(f"Busy Wait: Held high. Waiting for {timeout:0.2f}s", stacklevel=2)
            time.sleep(timeout)
            return

        # The busy line is requested with edge_detection=Edge.RISING, so the first
        # event is the rising edge we're waiting for.
        if gpiodevice.wait_for_edge(self._gpio, self.busy_pin, timeout) is None:
            warnings.warn(f"Busy Wait: Timed out after {timeout:0.2f}s", stacklevel=2)
            return

    def _update(self, buf):
        """Update display.

        Dispatches display update to correct driver.

        """
        self.setup()
        self._send_command(UC8159_DTM1, buf)

        self._send_command(UC8159_PON)
        self._busy_wait(0.2)

        self._send_command(UC8159_DRF)
        self._busy_wait(32.0)

        self._send_command(UC8159_POF)
        self._busy_wait(0.2)
''',
    'e640': r'''class Inky:
    def _busy_wait(self, timeout=40.0):
        """Wait for busy/wait pin."""
        # If the busy_pin is *high* (pulled up by host)
        # then assume we're not getting a signal from inky
        # and wait the timeout period to be safe.
        if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            time.sleep(timeout)
            return

        t_start = time.time()
        while self._gpio.get_value(self.busy_pin) != Value.ACTIVE:
            time.sleep(0.1)
            if time.time() - t_start > timeout:
                warnings.warn(f"Busy Wait: Timed out after {timeout:0.2f}s", stacklevel=2)
                return

    def _update(self, buf):
        """Update display.

        Dispatches display update to correct driver.

        """
        self.setup()

        self._send_command(EL640_DTM1, buf)
        self._send_command(EL640_PON)
        self._busy_wait(0.3)

        # second setting of the BTST2 register
        self._send_command(EL640_BTST2, [0x6F, 0x1F, 0x17, 0x47])

        self._send_command(EL640_DRF, [0x00])
        self._busy_wait(40.0)

        self._send_command(EL640_POF, [0x00])
        self._busy_wait(0.3)
''',
    'e673': r'''class Inky:
    def _busy_wait(self, timeout=40.0):
        """Wait for busy/wait pin."""
        # If the busy_pin is *high* (pulled up by host)
        # then assume we're not getting a signal from inky
        # and wait the timeout period to be safe.
        if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            time.sleep(timeout)
            return

        t_start = time.monotonic()
        while self._gpio.get_value(self.busy_pin) != Value.ACTIVE:
            time.sleep(0.1)
            if time.monotonic() - t_start > timeout:
                warnings.warn(f"Busy Wait: Timed out after {timeout:0.2f}s", stacklevel=2)
                return

    def _update(self, buf):
        """Update display.

        Dispatches display update to correct driver.

        """
        self.setup()

        self._send_command(EL673_DTM1, buf)
        self._send_command(EL673_PON)
        self._busy_wait(0.3)

        # second setting of the BTST2 register
        self._send_command(EL673_BTST2, [0x6F, 0x1F, 0x17, 0x49])

        self._send_command(EL673_DRF, [0x00])
        self._busy_wait(32.0)

        self._send_command(EL673_POF, [0x00])
        self._busy_wait(0.3)

        self._send_command(EL673_PSR, [0x4F, 0x6E])
        self._busy_wait(0.3)
''',
    'el133uf1': r'''class Inky:
    def _busy_wait(self, timeout=40.0):
        """Wait for busy/wait pin."""
        # If the busy_pin is *high* (pulled up by host)
        # then assume we're not getting a signal from inky
        # and wait the timeout period to be safe.
        if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            time.sleep(timeout)
            return

        t_start = time.monotonic()
        while self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            time.sleep(0.1)
            if time.monotonic() - t_start > timeout:
                warnings.warn(f"Busy Wait: Timed out after {timeout:0.2f}s", stacklevel=2)
                return

    def _refresh_wait(self, timeout=65.0):
        """Wait for a display refresh to complete.

        Unlike ``_busy_wait``, the EL133UF1 BUSY line is *active-LOW* during a
        refresh: after DRF the line drops LOW (INACTIVE) while the panel is
        updating, then returns HIGH (ACTIVE) once the refresh is done. Poll for
        the line to first assert busy (LOW), then wait for it to clear (HIGH),
        so we never send POF mid-refresh (which can latch the panel into a fault
        that only full power removal recovers).
        """
        t_start = time.monotonic()

        # Wait for the panel to assert BUSY (line drops LOW) after DRF.
        while self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            if time.monotonic() - t_start > timeout:
                warnings.warn(f"Refresh Wait: Timed out waiting for busy after {timeout:0.2f}s", stacklevel=2)
                return
            time.sleep(0.01)

        # Wait for the refresh to complete (line returns HIGH).
        while self._gpio.get_value(self.busy_pin) == Value.INACTIVE:
            if time.monotonic() - t_start > timeout:
                warnings.warn(f"Refresh Wait: Timed out after {timeout:0.2f}s", stacklevel=2)
                return
            time.sleep(0.1)

    def _update(self, buf_a, buf_b):
        """Update display.
        Dispatches display update to correct driver.
        """
        self.setup()

        self._send_command(EL133UF1_DTM, CS0_SEL, buf_a)
        self._send_command(EL133UF1_DTM, CS1_SEL, buf_b)

        self._send_command(EL133UF1_PON, CS_BOTH_SEL)
        self._busy_wait(0.2)

        self._send_command(EL133UF1_DRF, CS_BOTH_SEL, [0x00])
        self._refresh_wait(65.0)

        self._send_command(EL133UF1_POF, CS_BOTH_SEL, [0x00])
        self._busy_wait(0.2)
''',
}
