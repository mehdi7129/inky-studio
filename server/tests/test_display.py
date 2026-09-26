"""Exercise the real controller with an in-memory driver, without touching GPIO."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from inky_web.inky.display import DisplayController
from inky_web.services import photos


def test_hardware_buffer_and_refresh_are_serialized(data_dir, png_factory):
    first, _ = photos.save(content=png_factory(color=(10, 0, 0)), original_filename="first.png")
    second, _ = photos.save(content=png_factory(color=(20, 0, 0)), original_filename="second.png")
    first_entered, second_entered, release_first, second_started = (Event() for _ in range(4))

    class Driver:
        buffer = None

        def __init__(self):
            self.shown = []

        def set_image(self, img, **kwargs):
            self.buffer = img.getpixel((0, 0))
            if self.buffer == (10, 0, 0):
                first_entered.set()
                assert release_first.wait(3)
            else:
                second_entered.set()

        def show(self):
            self.shown.append(self.buffer)

    driver = Driver()
    display = DisplayController()
    display._impl = driver
    display._is_mock = False

    def show_second():
        second_started.set()
        display.display_image(photos.path_for(second.id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(display.display_image, photos.path_for(first.id))
        try:
            assert first_entered.wait(3)
            two = pool.submit(show_second)
            assert second_started.wait(3)
            assert not second_entered.wait(0.1)
        finally:
            release_first.set()
        one.result(timeout=3)
        two.result(timeout=3)

    assert driver.shown == [(10, 0, 0), (20, 0, 0)]
