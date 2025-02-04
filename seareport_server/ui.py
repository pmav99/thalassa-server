# mypy: disable-error-code=no-untyped-call
from __future__ import annotations

import gc
import logging
import operator
import os.path
import sys
import time
import typing as T
from functools import reduce

import adlfs
import decorator
import geoviews as gv
import panel as pn
import param
import xarray as xr
from azure.identity.aio import AzureCliCredential
from azure.identity.aio import ChainedTokenCredential
from azure.identity.aio import EnvironmentCredential
from azure.identity.aio import ManagedIdentityCredential
from thalassa import api
from thalassa import utils

# from thalassa import normalization


logger = logging.getLogger(__name__)
logger.error(logger.handlers)

DATA_DIR = "./data/"
DATA_GLOB = DATA_DIR + os.path.sep + "*"


@decorator.contextmanager
def timer(
    msg: str = "",
    log_func: T.Callable[..., None] = logger.debug,
    stacklevel: int = 0,
) -> T.Generator[T.Any, T.Any, T.Any]:
    t1 = time.perf_counter()
    yield
    elapsed = time.perf_counter() - t1
    if not stacklevel:
        stacklevel = 5 if sys._getframe(2).f_code.co_filename.endswith("site-packages/decorator.py") else 3
    log_func("%s: %.9fs", msg, elapsed, stacklevel=stacklevel)


def get_credential() -> ChainedTokenCredential:
    credential_chain = (
        EnvironmentCredential(),
        AzureCliCredential(),
        ManagedIdentityCredential(),
    )
    credential = ChainedTokenCredential(*credential_chain)
    return credential


def get_blob_fs(
    storage_account_name: str,
    credential: ChainedTokenCredential | None = None,
) -> adlfs.AzureBlobFileSystem:
    if not credential:
        credential = get_credential()
    file_system = adlfs.AzureBlobFileSystem(
        account_name=storage_account_name,
        credential=credential,
        anon=False,
    )
    return file_system


CREDENTIAL = get_credential()

STORAGE_OPTIONS = {
    "account_name": "seareport",
    "credential": CREDENTIAL,
}

MISSING_DATA_DIR = pn.pane.Alert(
    f"## Directory <{DATA_DIR}> is missing. Please create it and add some suitable netcdf files.",
    alert_type="danger",
)
EMPTY_DATA_DIR = pn.pane.Alert(
    f"## Directory <{DATA_DIR}> exists but it is empty. Please add some suitable netcdf files.",
    alert_type="danger",
)
CHOOSE_FILE = pn.pane.Alert(
    "## Please select a *Dataset* and click on the **Render** button.",
    alert_type="info",
)
UNKNOWN_FORMAT = pn.pane.Alert(
    "## The selected dataset is in an unknown format. Please choose a different file.",
    alert_type="danger",
)
PLEASE_RENDER = pn.pane.Alert(
    "## Please click on the **Render** button to visualize the selected *Variable*",
    alert_type="info",
)


# Create a custom FloatInput without a spinner
class FloatInputNoSpinner(pn.widgets.input._FloatInputBase):
    pass


def choose_info_message() -> pn.pane.Alert:
    # if not pathlib.Path(DATA_DIR).is_dir():
    #     message = MISSING_DATA_DIR
    # elif not sorted(filter(normalization.can_be_inferred, glob.glob(DATA_GLOB))):
    #     message = EMPTY_DATA_DIR
    # else:
    #     message = CHOOSE_FILE
    message = CHOOSE_FILE
    return pn.Row(message, width_policy="fit")


def get_spinner() -> pn.Column:
    """Return a `pn.Column` with an horizontally/vertically aligned spinner."""
    column = pn.Column(
        pn.layout.Spacer(height=50),
        pn.Row(
            pn.layout.HSpacer(),
            pn.Row(pn.indicators.LoadingSpinner(value=True, width=150, height=150)),
            pn.layout.HSpacer(),
            width_policy="fit",
        ),
    )
    return column


def get_colorbar_row(
    raster: gv.DynamicMap,
    clim_min_value: float | None = None,
    clim_max_value: float | None = None,
) -> pn.Row:
    clim_min = FloatInputNoSpinner(name="Colorbar min", align="auto", value=clim_min_value)
    clim_max = FloatInputNoSpinner(name="Colorbar max", align="center", value=clim_max_value)
    clim_apply = pn.widgets.Button(name="Apply", button_type="primary", align="end")
    clim_reset = pn.widgets.Button(name="reset", button_type="primary", align="end")
    # Set Input widgets JS callbacks
    clim_min.jslink(raster, value="color_mapper.low")
    clim_max.jslink(raster, value="color_mapper.high")
    # Set button JS callbacks
    clim_apply.jscallback(
        clicks="""
            console.log(clim_min.value)
            console.log(clim_max.value)
            console.log(raster.right[0].color_mapper.low)
            console.log(raster.right[0].color_mapper.high)
            raster.right[0].color_mapper.low = clim_min.value
            raster.right[0].color_mapper.high = clim_max.value
            raster.right[0].color_mapper.change.emit()
        """,
        args={"raster": raster, "clim_min": clim_min, "clim_max": clim_max},
    )
    clim_reset.jscallback(
        clicks="""
            //clim_min.value = null
            //clim_max.value = null
            raster.right[0].color_mapper.low = null
            raster.right[0].color_mapper.high = null
            raster.right[0].color_mapper.change.emit()
        """,
        args={"raster": raster, "clim_min": clim_min, "clim_max": clim_max},
    )
    spacer = pn.layout.HSpacer()
    row = pn.Row(
        spacer,
        clim_min,
        clim_max,
        clim_apply,
        clim_reset,
    )
    return row


def get_dataset(dataset_file: str) -> xr.Dataset:
    uri = f"az://{dataset_file}"
    ds: xr.Dataset = api.open_dataset(
        uri,
        engine="zarr",
        normalize=True,
        storage_options=STORAGE_OPTIONS,
        chunks={},
    )
    # ds = crop(ds, shapely.box(-180, -74.9, 180, 74.9))
    return ds


# @pn.cache(max_items=5, policy='LRU')
# def get_dataset(dataset_file: str) -> xr.Dataset:
#     ds: xr.Dataset = api.open_dataset(
#         dataset_file,
#         engine="zarr",
#         normalize=True,
#         chunks={},
#     )
#     print(ds)
#     return ds


def get_dataset_files() -> list[str]:
    blob = get_blob_fs("seareport")
    files = list(reversed(blob.ls("global-v1/")))[1:]
    return files


class SeareportUI:
    """
    This UI is supposed to be used with a Bootstrap-like template supporting
    a "main" and a "sidebar":
    - `sidebar` will contain the widgets that control what will be rendered in the main area.
      E.g. things like which `source_file` to use, which timestamp to render etc.
    - `main` will contain the rendered graphs.
    In a nutshell, an instance of the `UserInteface` class will have two private attributes:
    - `_main`
    - `_sidebar`
    These objects should be of `pn.Column` type. You can append
    """

    def __init__(self, fontscale: float = 1.4) -> None:
        self._dataset: xr.Dataset
        self._tiles: gv.Tiles = api.get_tiles()
        self._mesh: gv.DynamicMap | None = None
        self._raster: gv.DynamicMap | None = None
        self._cbar_row: pn.Row | None = None
        self._fontscale = fontscale

        # UI components
        self._main = pn.Column(CHOOSE_FILE, sizing_mode="scale_width")
        self._sidebar = pn.Column()

        # Define widgets
        self.dataset_file = pn.widgets.Select(
            name="Dataset file",
            options=["", *get_dataset_files()],
            # options=["", *pathlib.Path("data").glob("*.zarr")],
        )
        self.variable = pn.widgets.Select(name="Plot Variable")
        self.ts_variable = pn.widgets.Select(name="Timeseries Variable")
        self.time = pn.widgets.Select(name="Time")
        self.keep_zoom = pn.widgets.Checkbox(name="Keep Zoom", value=True)
        self.show_mesh = pn.widgets.Checkbox(name="Overlay Mesh")
        # self.show_timeseries = pn.widgets.Checkbox(name="Show Timeseries")
        self.render_button = pn.widgets.Button(name="Render", button_type="primary")

        # Setup UI
        self._sidebar.append(
            pn.Column(
                pn.WidgetBox(
                    self.dataset_file,
                    self.variable,
                    self.time,
                    self.ts_variable,
                    self.keep_zoom,
                    self.show_mesh,
                ),
                self.render_button,
            ),
        )
        logger.debug("UI setup: done")

        # Define callbacks
        self.dataset_file.param.watch(fn=self._update_dataset_file, parameter_names="value")
        self.variable.param.watch(fn=self._on_variable_change, parameter_names="value")
        # self.ts_variable.param.watch(fn=self._on_variable_change, parameter_names="value")
        # self.show_timeseries.param.watch(fn=self._on_show_timeseries_clicked, parameter_names="value")
        self.render_button.on_click(callback=self._update_main)

        # Periodically update the dataset files
        pn.state.schedule_task("update_dataset_files", self._update_dataset_files, period="300s")

        logger.debug("Callback definitions: done")

        self._reset_ui(message=choose_info_message())

    def _update_dataset_files(self) -> None:
        dataset_files = get_dataset_files()
        logger.debug("Updated dataset files")
        self.dataset_file.param.set_param(options=["", *dataset_files])

    def _reset_colorbar(self) -> None:
        self._cbar_row = None

    def _reset_ui(self, message: pn.pane.Alert) -> None:
        self.variable.param.set_param(options=[], disabled=True)
        self.ts_variable.param.set_param(options=[], disabled=True)
        self.time.param.set_param(options=[], disabled=True)
        self.keep_zoom.param.set_param(disabled=True)
        self.show_mesh.param.set_param(disabled=True)
        # self.show_timeseries.param.set_param(disabled=True)
        self.render_button.param.set_param(disabled=True)
        with timer("main: reset UI"):
            self._main.objects = [message]
        self._mesh = None
        self._raster = None
        self._reset_colorbar()

    def _update_dataset_file(self, event: param.Event) -> None:
        logger.debug("Update dataset: Start")
        dataset_file = self.dataset_file.value
        if not dataset_file:
            logger.debug("No dataset has been selected. Resetting the UI.")
            self._reset_ui(message=CHOOSE_FILE)
        else:
            try:
                logger.debug("Trying to normalize the selected dataset: %s", dataset_file)
                self._dataset = get_dataset(dataset_file)
            except ValueError:
                logger.exception("Normalization failed. Resetting the UI")
                self._reset_ui(message=UNKNOWN_FORMAT)
            else:
                logger.exception("Normalization succeeded. Setting widgets")
                variables = utils.filter_visualizable_data_vars(
                    self._dataset,
                    self._dataset.data_vars.keys(),
                )
                time_dependent_variables = [""] + [
                    var for var in variables if "time" in self._dataset[var].dims
                ]
                default_variable = "elev_max" if "elev_max" in variables else variables[0]
                self.variable.param.set_param(options=variables, value=default_variable, disabled=False)
                self.ts_variable.param.set_param(
                    options=time_dependent_variables,
                    value=time_dependent_variables[0],
                    disabled=False,
                )
                self.keep_zoom.param.set_param(disabled=False)
                self.show_mesh.param.set_param(disabled=False)
                with timer("main: update_dataset_file"):
                    self._main.objects = [PLEASE_RENDER]
                self._reset_colorbar()
        logger.debug("Update dataset: Finish")

    def _on_variable_change(self, event: param.Event) -> None:
        logger.warning(event)
        try:
            ds = self._dataset
            variable = self.variable.value
            # handle time
            if variable and "time" in ds[variable].dims:
                # self.show_timeseries.param.set_param(disabled=False)
                # self.time.param.set_param(options=["max", *ds.time.to_numpy()], disabled=False)
                self.time.param.set_param(options=ds.time.to_series().tolist(), disabled=False)
            else:
                # self.show_timeseries.param.set_param(disabled=True)
                self.time.param.set_param(options=[], disabled=True)
            self.render_button.param.set_param(disabled=False)
            self._reset_colorbar()
        except Exception:
            logger.exception("error")
            raise

    def _debug_ui(self) -> None:
        logger.info("Widget values:")
        widgets = [obj for (name, obj) in self.__dict__.items() if isinstance(obj, pn.widgets.Widget)]
        for widget in widgets:
            logger.error("%s: %s", widget.name, widget.value)

    @timer("MAIN")
    def _update_main(self, event: param.Event) -> None:
        logger.info("Rendering: start")
        try:
            # XXX For some reason, which I can't understand
            # Inside this specific callback, the logger requires to be WARN and above...
            logger.warning("Updating main")
            self._debug_ui()

            # First of all, retrieve the lon and lat ranges of the previous plot (if there is one)
            # This will allow us to restore the zoom level after re-clicking on the Render button.
            if self.keep_zoom.value and self._raster:
                lon_range = self._raster.range("lon")
                lat_range = self._raster.range("lat")
            else:
                lon_range = None
                lat_range = None
            logger.error("lon_range: %s", lon_range)
            logger.error("lat_range: %s", lat_range)

            # Since each graph takes up to a few GBs of RAM, before we create the new graph we should
            # remove the old one. In order to do so we need to remove *all* the references to the old
            # raster. This includes: - the `_main` column
            # For the record, we render a Spinner in order to show to the users that computations are
            # happening behind the scenes
            self._main_plot = None
            self._raster = None
            with timer("Rendering: Spinner"):
                with timer("main: spinner"):
                    self._main.objects = [*get_spinner().objects]

            # Now let's make an explicit call to `gc.collect()`. This will make sure
            # that the references to the old raster are really removed before the creation
            # of the new one, thus RAM usage should remain low(-ish).
            gc.collect()

            # Each time a graph is rendered, data are loaded from the dataset
            # This increases the RAM usage over time. E.g. when loading the second variable,
            # the first one remains in RAM.
            # In order to avoid this, we re-open the dataset in order to get a clean Dataset
            # instance without anything loaded into memory

            with timer("Rendering: Open dataset"):
                ds = get_dataset(self.dataset_file.value)

            # local variables
            variable = self.variable.value
            timestamp = self.time.value

            # We want to filter the dataset. But...
            # For the raster plot we may need to filter on time
            # While for the timeseries we don't filter at all
            # So let's keep a reference for the timeseries and filter on time afterwards
            ds_ts = ds
            if timestamp:
                ds = ds.sel(time=timestamp)

            # create plots
            # What we do here needs some explaining.
            # A prerequisite for generating the DynamicMaps is to create the trimesh.
            # The trimesh is needed for both the wireframe and the raster.
            # No matter what widget we change (variable, timestamp), we need to generate
            # a new trimesh object. This is why the trimesh is a local variable and not an
            # instance attribute (which would be cached)
            trimesh = api.create_trimesh(ds, variable=variable)

            # The wireframe is not always needed + it is always the same regardless of the variable.
            # So, we will generate it on the fly the first time we need it.
            # Therefore, we store it as an instance attribute in order to reuse it in future renders
            if self.show_mesh.value and self._mesh is None:
                with timer("Rendering: Creating mesh"):
                    self._mesh = api.get_wireframe(
                        trimesh,
                        x_range=lon_range,
                        y_range=lat_range,
                        hover=True,
                    )

            # The raster needs to be stored as an instance attribute, too, because we want to
            # be able to restore the zoom level whenever we re-render
            with timer("Rendering: Rendering raster"):
                self._raster = api.get_raster(trimesh, x_range=lon_range, y_range=lat_range)

            # In order to control dynamically the ColorBar of the raster we create
            # a `panel.Row` with extra widgets.
            # When re-rendering we want to preserve the values of the Colobar widgets
            with timer("Rendering: Creating cbar_row"):
                clim_min = 0.2 if "elev" in variable else None
                clim_max = 0.8 if "elev" in variable else None
                if self._cbar_row:
                    clim_min = self._cbar_row[1].value  # type: ignore[union-attr]
                    clim_max = self._cbar_row[2].value  # type: ignore[union-attr]
                self._cbar_row = get_colorbar_row(
                    raster=self._raster,
                    clim_min_value=clim_min,
                    clim_max_value=clim_max,
                )

            # Construct the list of objects that will be part of the main overlay
            # Depending on the choices of the user, this list may be populated with
            # additional items later
            main_overlay_components = [self._tiles, self._raster.opts(fontscale=self._fontscale)]

            # Render the wireframe if necessary
            if self.show_mesh.value:
                main_overlay_components.append(self._mesh)

            # The ts_plot is only plotted if a timeseries variables has been selected.
            # Nevertheless, we can add `None` to a `pn.Row/Column` and
            # that value will be ignored, which allows us to simplify the way we define
            # the rendable objects
            ts_row = None
            if self.ts_variable.value:
                with timer("Rendering: Rendering TS"):
                    ts_plot = api.get_tap_timeseries(
                        ds=ds_ts,
                        variable=self.ts_variable.value,
                        source_raster=self._raster,
                        fontscale=self._fontscale,
                    ).opts(responsive=True)
                    ts_row = pn.Column(
                        pn.layout.Spacer(height=50),
                        ts_plot,
                    )

            with timer("Rendering: reduce"):
                main_overlay = reduce(operator.mul, main_overlay_components)

            # For the record, (and this is probably a panel bug), if we use
            #     self._main.append(ts_plot)
            # then the timeseries plot does not get updated each time we click on the
            # DynamicMap. By replacing the `objects` though, then the updates work fine.
            with timer("Rendering: replacing objects - create list"):
                ll = [row for row in (main_overlay, self._cbar_row, ts_row) if row is not None]
                self._main.clear()
                self._main.objects = ll

        except Exception:
            logger.exception("Something went wrong")
            raise
        finally:
            logger.info("Rendering: finished")

    @property
    def sidebar(self) -> pn.Column:
        return self._sidebar

    @property
    def main(self) -> pn.Column:
        return self._main
