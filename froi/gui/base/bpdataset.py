# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:

"""
Dataset definition class for PyBP GUI system.
"""

import re
import os
import sys

import nibabel as nib
import numpy as np
from PyQt4.QtCore import *
from PyQt4.QtGui import *

from froi.algorithm import array2qimage as aq
from labelconfig import LabelConfig


class DoStack(QObject):
    """
    For Undo and Redo
    """
    stack_changed = pyqtSignal()

    def __init__(self):
        super(QObject, self).__init__()
        self._stack = []

    def push(self, v):
        self._stack.append(v)
        self.stack_changed.emit()

    def pop(self):
        t = self._stack.pop()
        self.stack_changed.emit()
        return t

    def clear(self):
        self._stack = []

    def stack_not_empty(self):
        if self._stack:
            return True
        else:
            return False

class VolumeDataset(object):
    """Base dataset in FreeROI GUI system."""
    def __init__(self, source, label_config_center, name=None, header=None, 
                 view_min=None, view_max=None, alpha=255, colormap='gray',
                 cross_pos=None):
        """
        Create a dataset from an NiftiImage which has following 
        atributes:
        
        Parameters
        ----------
        source : Nifti file path or 3D/4D numpy array
            Nifti dataset, specified either as a filename (single file 3D/4D 
            image) or a 3D/4D numpy array. When source is a numpy array,
            parameter header is required.
        label_config : label configuration
        name : name of the volume
            volume name.
        header : nifti1 header structure
            Nifti header structure.
        view_min : scalar or None
            The lower limitation of data value which can be seen.
        view_max : scalar
            The upper limitation of data value which can be seen.
        alpha: int number (0 - 255)
            alpha channel value, 0 indicates transparency. Default is 255.
        colormap : string
            The string can represents the colormap used for corresponding
            values, it can be 'gray', 'red2yellow', 'blue2green', 'ranbow'...
        cross_pos : a list containing [x, y, z]
            Default is None

        Returns
        -------
        VolumeDataset

        """
        if isinstance(source, np.ndarray):
            self._data = np.rot90(source)
            if name == None:
                self._name = 'new_image'
            else:
                self._name = str(name)
            if not isinstance(header, nib.nifti1.Nifti1Header):
                raise ValueError("Parameter header must be specified!")
            elif header.get_data_shape() == source.shape:
                self._header = header
                self._img = None
            else:
                raise ValueError("Data dimension does not match.")
        else:
            self._img = nib.load(source)
            self._header = self._img.get_header()
            basename = os.path.basename(source.strip('/'))
            self._name = re.sub(r'(.*)\.nii(\.gz)?', r'\1', basename)
            self.save_mem_load()

        # For convenience, define a shift variable
        self._y_shift = self.get_data_shape()[1] - 1

        if view_min == None:
            self._view_min = self._data.min()
        else:
            self._view_min = view_min

        if view_max == None:
            self._view_max = self._data.max()
        else:
            self._view_max = view_max

        self._alpha = alpha
        self._colormap = colormap
        self._rgba_list = range(self.get_data_shape()[2])
 
        # bool status for the item
        self._visible = True
        if len(self.get_data_shape()) == 3:
            self._4d = False
        else:
            self._4d = True
        self._time_point = 0

        # temporal variant for OrthView
        self._cross_pos = cross_pos

        # define a dictionary 
        self.label_config_center = label_config_center
        self.label_config_center.single_roi_view_update.connect(self.update_single_roi)
        
        # undo redo stacks
        self.undo_stack = DoStack()
        self.redo_stack = DoStack()

        self.update_rgba()
        if self._cross_pos:
            self.update_orth_rgba()

    def save_mem_load(self):
        """Load data around current time-point."""
        if len(self.get_data_shape())==4 and self._img:
            data = np.zeros(self.get_data_shape())
            self._data = np.rot90(data)
            self._loaded_time_list = [0]
            self._data[..., 0] = np.rot90(self._img.dataobj[..., 0])
        else:
            self._loaded_time_list = [0]
            data = self._img.get_data(caching='unchanged')
            self._data = np.rot90(data)

    def get_data_shape(self):
        """Get shape of data."""
        return self._header.get_data_shape()

    def _rendering_factory(self):
        """Return a rendering factory according to the display setting."""
        def shadow(array):
            if not isinstance(self._colormap, LabelConfig):
                colormap = str(self._colormap)
            else:
                colormap = self._colormap.get_colormap()
            try:
                current_roi = self.label_config_center.get_drawing_value()
            except ValueError:
                current_roi = None
            return aq.array2qrgba(array, self._alpha, colormap,
                                  normalize=(self._view_min, self._view_max), 
                                  roi=current_roi)
        return shadow

    def update_single_roi(self):
        """Update the view with single ROI colormap."""
        if self._colormap == 'single ROI':
            self.update_rgba()
            if self._cross_pos:
                self.update_orth_rgba()
            self.label_config_center.single_roi_view_update_for_model.emit() 

    def update_rgba(self, index=None):
        """Create a range of qrgba array for display."""
        # return a rendering factory
        f = self._rendering_factory()

        if index == None:
            if self.is_4d():
                layer_list = [self._data[..., i, self._time_point] for i in 
                                    range(self.get_data_shape()[2])]
            else:
                layer_list = [self._data[..., i] for i in 
                                    range(self.get_data_shape()[2])]
            self._rgba_list = map(f, layer_list)
        else:
            if self.is_4d():
                self._rgba_list[index] = f(self._data[..., index,
                                                      self._time_point])
            else:
                self._rgba_list[index] = f(self._data[..., index])

    def set_cross_pos(self, cross_pos):
        """ Update RGBA data in sagital, axial and coronal directions."""
        if self._cross_pos:
            if not cross_pos[0] == self._cross_pos[0]:
                self._cross_pos[0] = cross_pos[0]
                self.update_sagital_rgba()
            if not cross_pos[1] == self._cross_pos[1]:
                self._cross_pos[1] = cross_pos[1]
                self.update_coronal_rgba()
            if not cross_pos[2] == self._cross_pos[2]:
                self._cross_pos[2] = cross_pos[2]
                self.update_axial_rgba()
        else:
            self._cross_pos = cross_pos
            self.update_sagital_rgba()
            self.update_coronal_rgba()
            self.update_axial_rgba()
    
    def update_orth_rgba(self):
        """Update the disply in orth view."""
        self.update_sagital_rgba()
        self.update_coronal_rgba()
        self.update_axial_rgba()

    def update_sagital_rgba(self):
        """Update the sagital disply in orth view."""
        f = self._rendering_factory()
        idx = self._cross_pos[0]
        if self.is_4d():
            self._sagital_rgba = f(np.rot90(self._data[:, idx, :,
                                                       self._time_point]))
        else:
            self._sagital_rgba = f(np.rot90(self._data[:, idx, :]))

    def update_axial_rgba(self):
        """Update the axial disply in orth view."""
        f = self._rendering_factory()
        idx = self._cross_pos[2]
        if self.is_4d():
            self._axial_rgba = f(self._data[:, :, idx, self._time_point])
        else:
            self._axial_rgba = f(self._data[:, :, idx])

    def update_coronal_rgba(self):
        """Update the coronal disply in orth view."""
        f = self._rendering_factory()
        idx = self._y_shift - self._cross_pos[1]
        if self.is_4d():
            self._coronal_rgba = f(np.rot90(self._data[idx, :, :,
                                                       self._time_point]))
        else:
            self._coronal_rgba = f(np.rot90(self._data[idx, :, :]))

    def set_alpha(self, alpha):
        """Set alpha value."""
        if isinstance(alpha, int):
            if alpha <= 255 and alpha >= 0:
                if self._alpha != alpha:
                    self._alpha = alpha
                    self.update_rgba()
                    if self._cross_pos:
                        self.update_orth_rgba()
        else:
            raise ValueError("Value must be an integer between 0 and 255.")

    def get_alpha(self):
        """Get alpha value."""
        return self._alpha

    def set_time_point(self, tpoint):
        """Set time point."""
        if self.is_4d():
            if isinstance(tpoint, int):
                if tpoint >= 0 and tpoint < self.get_data_shape()[3]:
                    if self._img:
                        if not tpoint in self._loaded_time_list:
                            self._data[..., tpoint] = \
                                    np.rot90(self._img.dataobj[..., tpoint])
                            self._loaded_time_list.append(tpoint)
                    self._time_point = tpoint
                    self.undo_stack.clear()
                    self.redo_stack.clear()
                    self.update_rgba()
                    if self._cross_pos:
                        self.update_orth_rgba()
            else:
                raise ValueError("Value must be an integer.")
    
    def get_time_point(self):
        """Get time point."""
        return self._time_point

    def set_view_min(self, view_min):
        """Set lower limition of display range."""
        try:
            view_min = float(view_min)
            self._view_min = view_min
            self.update_rgba()
            if self._cross_pos:
                self.update_orth_rgba()
        except ValueError:
            print "view_min must be a number."

    def get_view_min(self):
        """Get lower limition of display range."""
        return self._view_min

    def set_view_max(self, view_max):
        """Set upper limition of display range."""
        try:
            view_max = float(view_max)
            self._view_max = view_max
            self.update_rgba()
            if self._cross_pos:
                self.update_orth_rgba()
        except ValueError:
            print"view_max must be a number."

    def get_view_max(self):
        """Get upper limition of display range."""
        return self._view_max
    
    def set_name(self, name):
        """Set item's name."""
        self._name = str(name)

    def get_name(self):
        """Get item's name."""
        return self._name

    def set_colormap(self, map_name):
        """Set item's colormap."""
        self._colormap = map_name
        self.update_rgba()
        if self._cross_pos:
            self.update_orth_rgba()

    def get_colormap(self):
        """Get item's colormap."""
        return self._colormap

    def set_visible(self, status):
        """Set visibility of the volume."""
        if isinstance(status, bool):
            if status:
                self._visible = True
            else:
                self._visible = False
        else:
            raise ValueError("Input must a bool.")

    def is_4d(self):
        """If the data is including several time points, return True."""
        return self._4d

    def is_visible(self):
        """Query the status of visibility."""
        return self._visible

    def get_rgba(self, index):
        """Get rgba array based on the index of the layer."""
        return self._rgba_list[index]

    def get_sagital_rgba(self):
        """Return the sagital rgba value.."""
        if self._sagital_rgba.tolist():
            return self._sagital_rgba
        else:
            return False

    def get_axial_rgba(self):
        """Return the axial rgba value."""
        if self._axial_rgba.tolist():
            return self._axial_rgba
        else:
            return False

    def get_coronal_rgba(self):
        """Return the coronal rgba value.."""
        if self._coronal_rgba.tolist():
            return self._coronal_rgba
        else:
            return False

    def set_voxel(self, x, y, z, value, ignore=True):
        """Set value of the voxel whose coordinate is (x, y, z)."""
        try:
            if isinstance(y, list):
                y_trans = [self._y_shift - item for item in y]
            if self.is_4d():
                orig_data = self._data[y_trans, x, z, self._time_point]
            else:
                orig_data = self._data[y_trans, x, z]
            if np.any(orig_data != 0) and not ignore:
                force = QMessageBox.question(None, "Replace?",
                        "Would you like to replace the original values?",
                        QMessageBox.Yes,
                        QMessageBox.No)
                if force == QMessageBox.No:
                    return
            if self.is_4d():
                self.undo_stack.push((x, y, z, self._data[y_trans, x, z,
                                                          self._time_point]))
                self._data[y_trans, x, z, self._time_point] = value
            else:
                self.undo_stack.push((x, y, z, self._data[y_trans, x, z]))
                self._data[y_trans, x, z] = value
            try:
                for z_ in range(min(z), max(z)+1):
                    self.update_rgba(z_)
            except TypeError:
                self.update_rgba(z)
            if self._cross_pos:
                self.update_orth_rgba()
        except:
            raise
            print "Input coordinates are invalid."

    def save2nifti(self, file_path):
        """Save to a nifti file."""
        #Define nifti1 datatype codes
        NIFTI_TYPE_UINT8 = 2  # unsigned char
        NIFTI_TYPE_INT16 = 4  # signed short
        NIFTI_TYPE_INT32 = 8  # signed int.
        NIFTI_TYPE_FLOAT32 = 16  # 32 bit float.
        NIFTI_TYPE_COMPLEX64 = 32  # 64 bit complex = 2 32 bit floats
        NIFTI_TYPE_FLOAT64 = 64  # 64 bit float = double.
        NIFTI_TYPE_RGB24 = 128  # 3 8 bit bytes.
        NIFTI_TYPE_INT8 = 256  # signed char.
        NIFTI_TYPE_UINT16 = 512  # unsigned short.
        NIFTI_TYPE_UINT32 = 768  # unsigned int.
        NIFTI_TYPE_INT64 = 1024  #signed long long.
        NIFTI_TYPE_UINT64 = 1280  # unsigned long long.
        NIFTI_TYPE_FLOAT128 = 1536  # 128 bit float = long double.
        NIFTI_TYPE_COMPLEX128 = 1792  #128 bit complex = 2 64 bit floats.
        NIFTI_TYPE_COMPLEX256 = 2048  # 256 bit complex = 2 128 bit floats
        NIFTI_TYPE_RGBA32 = 2304  # 4 8 bit bytes.

        #Detect the data type of the input data.
        data_type = {
            np.uint8: NIFTI_TYPE_UINT8,
            np.uint16: NIFTI_TYPE_UINT16,
            np.uint32: NIFTI_TYPE_UINT32,
            np.float32: NIFTI_TYPE_FLOAT32,
            np.int16: NIFTI_TYPE_INT16,
            np.int32: NIFTI_TYPE_INT32,
            np.int8: NIFTI_TYPE_INT8
            }
        if sys.maxint > 2 ** 32: # The platform is 64 bit
            data_type[np.float128] = NIFTI_TYPE_FLOAT128
            data_type[np.float64] = NIFTI_TYPE_FLOAT64
            data_type[np.int64] = NIFTI_TYPE_INT64
            data_type[np.uint64] = NIFTI_TYPE_UINT64
            data_type[np.complex64] = NIFTI_TYPE_COMPLEX64
            data_type[np.complex128] = NIFTI_TYPE_COMPLEX128
            data_type[np.complex256] = NIFTI_TYPE_COMPLEX256

        data = np.rot90(self._data, 3)
        if data_type.has_key(data.dtype.type):
            self._header['datatype'] = data_type[data.dtype.type]

        self._header['cal_max'] = data.max()
        self._header['cal_min'] = 0
        image = nib.nifti1.Nifti1Image(data, None, self._header)
        nib.nifti1.save(image, file_path)

    def get_label_config(self):
        """Return the label config object."""
        return self.label_config_center

    def undo_stack_not_empty(self):
        """Return status of the undo stack."""
        return self.undo_stack.stack_not_empty()

    def redo_stack_not_empty(self):
        return self.redo_stack.stack_not_empty()

    def undo(self):
        """Resume to the last step."""
        if self.undo_stack:
            voxel_set = self.undo_stack.pop()
            self.set_voxel(*voxel_set, ignore=True)
            self.redo_stack.push(self.undo_stack.pop())
            return voxel_set[2]
        return None

    def redo(self):
        """Forward to the next step."""
        if self.redo_stack:
            voxel_set = self.redo_stack.pop()
            self.set_voxel(*voxel_set, ignore=True)
            return voxel_set[2]
        return None

    def connect_undo(self, slot):
        """Connect the event to the undo slot.
        """
        self.undo_stack.stack_changed.connect(slot)

    def connect_redo(self, slot):
        """Connect the event to the undo slot."""
        self.redo_stack.stack_changed.connect(slot)

    def get_header(self):
        """Get the header of the data.."""
        return self._header

    def get_value(self, xyz, time_course=False):
        """Get the valoue based on the given x,y,z cordinate."""
        if not time_course:
           if self.is_4d():
               return self._data[self._y_shift - xyz[1],
                                 xyz[0], xyz[2], self._time_point]
           else:
               return self._data[self._y_shift - xyz[1], xyz[0], xyz[2]]
        else:
            if self.is_4d() and self._img:
               data = self.get_raw_data()
               data = np.rot90(data)
               return data[self._y_shift - xyz[1], xyz[0], xyz[2], :]
            elif self.is_4d():
               return self._data[self._y_shift - xyz[1], xyz[0], xyz[2], :]
            else:
               return self._data[self._y_shift - xyz[1], xyz[0], xyz[2]]

    def get_lthr_data(self):
        """Return whole data which low-thresholded."""
        # FIXME one time point or whole data
        temp = self._data.copy()
        temp[temp <= self._view_min] = 0
        return temp

    def get_lthr_raw_data(self):
        """
        Return the low threshold of the raw data.
        """
        temp = self._data.copy()
        temp[temp <= self._view_min] = 0
        return np.rot90(temp, 3)

    def get_raw_data(self):
        """Return the raw data."""
        if self._img and self.is_4d():
            temp = self._img.get_data(caching='unchanged')
            temp = np.rot90(temp)
            for tp in self._loaded_time_list:
                temp[..., tp] = self._data[..., tp]
        else:
            temp = self._data.copy()

        return np.rot90(temp, 3)

    def get_value_label(self, value):
        """Return the label of the given value."""
        return self.label_config.get_index_label(value)

    def set_label(self, label_config):
        """Set the label using the given label_config parameter."""
        self.label_config = label_config

    def is_label_global(self):
        """Return the value whether the label is global."""
        return self.label_config.is_global

    def get_roi_coords(self, roi):
        """Return cordinates of the given roi."""
        if self.is_4d():
            data = self._data[..., self._time_point]
        else:
            data = self._data
        coord = (data==roi).nonzero()
        #return (data==roi).nonzero()
        return (coord[1], self._y_shift - coord[0], coord[2])

    def get_coord_val(self, x, y, z):
        """Return value based on the given x,y,z cordinate."""
        if self.is_4d():
            #return self._data[y, x, z, self._time_point]
            return self._data[self._y_shift - y, x, z, self._time_point]
        else:
            #return self._data[y, x, z]
            return self._data[self._y_shift - y, x, z]

    def duplicate(self):
        """Return a duplicated image."""
        dup_img = VolumeDataset(source=self.get_raw_data(),
                                label_config_center=self.get_label_config(),
                                name=self.get_name()+'_duplicate',
                                header=self.get_header(),
                                view_min=self.get_view_min(),
                                view_max=self.get_view_max(),
                                alpha=self.get_alpha(),
                                colormap=self.get_colormap())
        return dup_img

