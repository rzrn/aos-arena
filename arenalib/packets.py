# Copyright © 2026 rzrn

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from pyspades.bytes import ByteWriter
from pyspades.loaders import Loader

EXTENSION_BASE           = 0x40
EXTENSION_DAMAGE_MARKERS = 0x20

class DamageMarkerPacket(Loader):
    id = EXTENSION_BASE + EXTENSION_DAMAGE_MARKERS

    def __init__(self):
        self.player_id  = 0
        self.hit_amount = 0

    def write(self, writer : ByteWriter):
        writer.writeUInt8LE(self.id)
        writer.writeUInt8LE(self.player_id)
        writer.writeUInt8LE(self.hit_amount)
