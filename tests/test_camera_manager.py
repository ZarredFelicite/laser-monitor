import sys
import types

import numpy as np

import camera_manager
from camera_manager import CameraInterface, CameraManager, Picamera2Camera, RpicamStillCamera
from config.config import ConfigManager


class FakePicamera2:
    instances = []

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.configurations = []
        self.controls = []
        self.start_count = 0
        self.capture_count = 0
        self.stop_count = 0
        self.close_count = 0
        self.cancel_count = 0
        self.capture_waits = []
        self.__class__.instances.append(self)

    def create_still_configuration(self, **kwargs):
        self.configurations.append(kwargs)
        return kwargs

    def configure(self, config):
        self.configured = config

    def set_controls(self, controls):
        self.controls.append(controls)

    def start(self):
        self.start_count += 1

    def capture_array(self, stream, wait=None):
        assert stream == 'main'
        self.capture_count += 1
        self.capture_waits.append(wait)
        return np.tile(
            np.array([11, 22, 33], dtype=np.uint8),
            (2, 3, 1),
        )

    def cancel_all_and_flush(self):
        self.cancel_count += 1

    def stop(self):
        self.stop_count += 1

    def close(self):
        self.close_count += 1


def install_fake_picamera2(monkeypatch):
    FakePicamera2.instances.clear()
    module = types.ModuleType('picamera2')
    module.Picamera2 = FakePicamera2
    monkeypatch.setitem(sys.modules, 'picamera2', module)


def test_picamera2_reuses_one_persistent_stream(monkeypatch):
    install_fake_picamera2(monkeypatch)
    camera = Picamera2Camera(camera_id=2)

    assert camera.open()
    assert camera.set_property('width', 1280)
    assert camera.set_property('height', 720)
    assert camera.set_property('fps', 10)
    assert camera.set_property('auto_exposure', False)
    assert camera.set_property('exposure', 200000)
    assert camera.set_property('brightness', 0.5)

    ok1, frame1 = camera.read()
    ok2, frame2 = camera.read()
    fake = FakePicamera2.instances[0]

    assert ok1 and ok2
    assert frame1.shape == (2, 3, 3)
    assert frame2.shape == (2, 3, 3)
    assert frame1[0, 0].tolist() == [11, 22, 33]
    assert fake.camera_id == 2
    assert fake.start_count == 1
    assert fake.capture_count == 4  # two warmup frames plus two requested frames
    assert fake.capture_waits == [10.0] * 4
    assert fake.configurations == [{
        'main': {'size': (1280, 720), 'format': 'RGB888'},
        'raw': None,
        'buffer_count': 1,
    }]
    assert fake.controls[0]['Brightness'] == 0.0
    assert fake.controls[0]['ExposureTime'] == 200000
    assert fake.controls[0]['FrameDurationLimits'] == (200000, 200000)

    camera.close()
    camera.close()
    assert fake.stop_count == 1
    assert fake.close_count == 1


def test_picamera2_capture_failure_restarts_stream_on_next_read(monkeypatch):
    install_fake_picamera2(monkeypatch)
    camera = Picamera2Camera(camera_id=0)
    assert camera.open()
    assert camera.read()[0]
    fake = FakePicamera2.instances[0]
    original_capture = fake.capture_array

    def fail_capture(stream, wait=None):
        raise RuntimeError("simulated capture failure")

    fake.capture_array = fail_capture
    assert camera.read() == (False, None)
    assert fake.stop_count == 1

    fake.capture_array = original_capture
    assert camera.read()[0]
    assert fake.start_count == 2

    fake.capture_array = lambda stream, wait=None: None
    assert camera.read() == (False, None)
    assert fake.stop_count == 2


def test_picamera2_capture_timeout_cancels_job_and_restarts_stream(monkeypatch):
    install_fake_picamera2(monkeypatch)
    camera = Picamera2Camera(camera_id=0)
    camera._config['warmup_frames'] = 0
    assert camera.open()
    fake = FakePicamera2.instances[0]

    def time_out(stream, wait=None):
        assert stream == 'main'
        assert wait == 10.0
        raise TimeoutError("camera frontend stopped responding")

    fake.capture_array = time_out
    assert camera.read() == (False, None)
    assert fake.cancel_count == 1
    assert fake.stop_count == 1
    assert not camera._started


def test_rpicam_fallback_uses_camera_id_and_one_buffer():
    camera = RpicamStillCamera(camera_id=3)
    camera._rpicam_path = '/usr/bin/rpicam-still'
    camera._help_text = '--camera --buffer-count --width --height'
    camera.available = True
    camera.set_property('width', 640)
    camera.set_property('height', 480)

    command = camera._build_rpicam_cmd('/tmp/frame.jpg')

    assert command[command.index('--camera') + 1] == '3'
    assert command[command.index('--buffer-count') + 1] == '1'
    assert command[command.index('--width') + 1] == '640'
    assert command[command.index('--height') + 1] == '480'


class UnavailableCamera(CameraInterface):
    available = False

    def __init__(self, camera_id=0):
        self.camera_id = camera_id

    def open(self):
        return False

    def close(self):
        pass

    def read(self):
        return False, None

    def set_property(self, prop, value):
        return False

    def get_property(self, prop):
        return None

    def is_opened(self):
        return False

    def get_info(self):
        return {'type': 'pi'}


def test_explicit_pi_does_not_silently_fall_back_to_usb(monkeypatch):
    monkeypatch.setattr(camera_manager, 'Picamera2Camera', UnavailableCamera)
    monkeypatch.setattr(camera_manager, 'RpicamStillCamera', UnavailableCamera)
    monkeypatch.setattr(
        camera_manager.USBCamera,
        'open',
        lambda self: (_ for _ in ()).throw(AssertionError('USB fallback attempted')),
    )

    manager = CameraManager()
    assert not manager.open_camera(0, 'pi')
    assert manager.camera is None


def test_camera_config_defaults_to_first_pi_camera_and_validates_backend():
    manager = ConfigManager()
    assert manager.config.camera.camera_id == 0
    assert manager.config.camera.camera_type == 'pi'

    manager.config.camera.camera_type = 'invalid'
    assert any('Camera type' in error for error in manager.validate_config())
