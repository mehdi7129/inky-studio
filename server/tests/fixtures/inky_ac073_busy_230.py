"""Inert source fixture; never import the upstream Linux/GPIO module.

Exact _busy_wait and _update methods from Pimoroni inky 2.3.0:
https://github.com/pimoroni/inky/blob/v2.3.0/inky/inky_ac073tc1a.py
Tag commit: 425c9688348910da73cf248b2d86aed17fa8cadc
Original file SHA256:
ab31898c7c291ce1b63a4c21798860a40e3a9c2a68e57dab933f882d5ecf5582

Tests compile these methods with inert GPIO, time, and command collaborators.
This is source-behaviour evidence, not a hardware qualification.

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

SOURCE = r'''class Inky:
    def _busy_wait(self, timeout=40.0):
        """Wait for busy/wait pin."""
        # If the busy_pin is *high* (pulled up by host)
        # then assume we're not getting a signal from inky
        # and wait the timeout period to be safe.
        if self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
            warnings.warn("Busy Wait: Held high. Waiting for {:0.2f}s".format(timeout))
            time.sleep(timeout)
            return

        event = self._gpio.wait_edge_events(timedelta(seconds=timeout))
        if not event:
            warnings.warn(f"Busy Wait: Timed out after {timeout:0.2f}s")
            return

        for event in self._gpio.read_edge_events():
            print(timeout, event)

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
'''
