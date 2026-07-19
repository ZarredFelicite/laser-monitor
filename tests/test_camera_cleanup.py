import sys
import types

from camera_manager import CameraManager


class FailingPicamera2:
    instances = []

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.close_count = 0
        self.__class__.instances.append(self)

    def create_still_configuration(self, **kwargs):
        return kwargs

    def configure(self, config):
        self.config = config

    def set_controls(self, controls):
        self.controls = controls

    def start(self):
        raise RuntimeError('simulated libcamera start failure')

    def close(self):
        self.close_count += 1


def test_explicit_picamera2_configuration_failure_closes_camera(monkeypatch):
    FailingPicamera2.instances.clear()
    module = types.ModuleType('picamera2')
    module.Picamera2 = FailingPicamera2
    monkeypatch.setitem(sys.modules, 'picamera2', module)

    manager = CameraManager()
    assert manager.open_camera(0, 'picamera2')
    assert not manager.configure_camera({'width': 640, 'height': 480})

    assert manager.camera is None
    assert manager.camera_type is None
    assert FailingPicamera2.instances[0].close_count == 1
