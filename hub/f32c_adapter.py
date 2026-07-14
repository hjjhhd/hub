"""Hub services for the WHEELTEC F32C two-axis gimbal."""

from .services import PeripheralAdapter


def _load_f32c_driver():
    """Load the driver copied from the sibling gimbal project at deployment."""
    try:
        from .f32c_gimbal import F32CGimbal
    except ImportError:
        try:
            from f32c_gimbal import F32CGimbal
        except ImportError:
            raise ImportError(
                "copy f32c_gimbal.py from the gimbal project beside main.py "
                "or into hub/ before enabling F32CGimbalAdapter"
            )
    return F32CGimbal


class F32CGimbalAdapter(PeripheralAdapter):
    """Expose a conservative, application-safe subset of ``F32CGimbal``.

    Movement replies mean that the F32C command was accepted by the UART
    driver.  They do not claim that the mechanical position has been reached.
    Persistent configuration commands are deliberately not exposed remotely.
    """

    _MODES = {
        "speed": "MODE_SPEED",
        "multi": "MODE_MULTI_T",
        "single": "MODE_SINGLE_T",
        "multi_direct": "MODE_MULTI_DIRECT",
        "single_direct": "MODE_SINGLE_DIRECT",
    }
    _METRICS = {
        "speed": "speed",
        "total_angle": "total_angle",
        "mechanical_angle": "mechanical_angle",
        "bus_voltage": "bus_voltage",
    }

    def __init__(self, x_id=1, y_id=2, timeout_ms=100, driver_class=None):
        self.x_id = x_id
        self.y_id = y_id
        self.timeout_ms = timeout_ms
        self.driver_class = driver_class
        self.gimbal = None

    def bind(self, hub, uart, config):
        PeripheralAdapter.bind(self, hub, uart, config)
        driver_class = self.driver_class or _load_f32c_driver()
        self.gimbal = driver_class(
            uart, x_id=self.x_id, y_id=self.y_id, timeout_ms=self.timeout_ms
        )

    def register_services(self, services):
        services.register("gimbal.enable", self.enable)
        services.register("gimbal.disable", self.disable)
        services.register("gimbal.set_mode", self.set_mode)
        services.register("gimbal.set_speed", self.set_speed)
        services.register("gimbal.set_acceleration", self.set_acceleration)
        services.register("gimbal.move_multiturn", self.move_multiturn)
        services.register("gimbal.move_singleturn", self.move_singleturn)
        services.register("gimbal.read", self.read)

    @staticmethod
    def _axes(args, default="all"):
        axis = args.get("axis", default)
        if axis == "all":
            return ("x", "y")
        if axis in ("x", "y"):
            return (axis,)
        raise ValueError("axis must be x, y, or all")

    @staticmethod
    def _number(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s must be a number" % name)
        return value

    @staticmethod
    def _integer(value, name):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("%s must be an integer" % name)
        return value

    def enable(self, args, context):
        axes = self._axes(args)
        for axis in axes:
            self.gimbal.enable(axis)
        return {"enabled": list(axes)}

    def disable(self, args, context):
        axes = self._axes(args)
        for axis in axes:
            self.gimbal.disable(axis)
        return {"disabled": list(axes)}

    def set_mode(self, args, context):
        mode_name = args.get("mode")
        mode_constant = self._MODES.get(mode_name)
        if mode_constant is None:
            raise ValueError("mode must be speed, multi, single, multi_direct, or single_direct")
        mode = getattr(self.gimbal, mode_constant)
        axes = self._axes(args)
        for axis in axes:
            self.gimbal.set_mode(axis, mode)
        return {"mode": mode_name, "axes": list(axes)}

    def set_speed(self, args, context):
        updated = self._set_axis_values(args, "speed", self.gimbal.set_speed)
        return {"speed": updated}

    def set_acceleration(self, args, context):
        updated = self._set_axis_values(
            args, "acceleration", self.gimbal.set_acceleration
        )
        return {"acceleration": updated}

    def _set_axis_values(self, args, field, setter):
        values = {}
        if "x" in args or "y" in args:
            for axis in ("x", "y"):
                if axis in args:
                    values[axis] = self._integer(args[axis], axis)
        else:
            if field not in args:
                raise ValueError("provide x/y values or %s with axis" % field)
            value = self._integer(args[field], field)
            for axis in self._axes(args):
                values[axis] = value
        if not values:
            raise ValueError("at least one axis value is required")
        for axis, value in values.items():
            setter(axis, value)
        return values

    def move_multiturn(self, args, context):
        moved = self._move(args, self.gimbal.move_multiturn)
        return {"commanded": moved, "mode": "multi"}

    def move_singleturn(self, args, context):
        moved = self._move(args, self.gimbal.move_singleturn)
        return {"commanded": moved, "mode": "single"}

    def _move(self, args, mover):
        moved = {}
        for axis in ("x", "y"):
            if axis in args:
                value = self._number(args[axis], axis)
                mover(axis, value)
                moved[axis] = value
        if not moved:
            raise ValueError("provide x and/or y angle")
        return moved

    def read(self, args, context):
        axis = args.get("axis")
        if axis not in ("x", "y"):
            raise ValueError("read requires axis x or y")
        metric = args.get("metric")
        method_name = self._METRICS.get(metric)
        if method_name is None:
            raise ValueError("metric must be speed, total_angle, mechanical_angle, or bus_voltage")
        value = getattr(self.gimbal, method_name)(axis, self.timeout_ms)
        return {"axis": axis, "metric": metric, "value": value}
