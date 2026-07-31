# Copyright © 2024–2026 rzrn
# Copyright © 2026 Spaten0

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

from time import monotonic
from math import floor

from piqueserver.utils import timeparse
from piqueserver.config import config

from pyspades.constants import GRENADE_KILL

arena_section      = config.section("arena")
afk_time_threshold = arena_section.option("afk_time_threshold", 15.0).get()



def get_spawnkill_count(connection, seconds):
    protocol = connection.protocol

    if not isinstance(connection, protocol.connection_class):
        return None

    t0 = monotonic()

    N = sum(t0 - t <= seconds for t in connection.spawnkill_time_deque)
    M = connection.spawnkill_time_deque.maxlen

    # Maybe its dumb, but this way it can be compared to .maxlen
    # outside of this function, so it can be used both in info command and
    # for punishment application
    if M is not None and N > M: return M + 1
    else: return N



def get_decayed_score(player):
    protocol = player.protocol
    ds = protocol.map_info.extensions

    config = ds.get("arena_spawnkill")
    if config is None: return 0

    decay_time = config.get("decay_time", 30)

    if not isinstance(player, protocol.connection_class):
        return 0

    if player.last_spawnkill_time == 0:
        return player.spawnkill_score

    T = monotonic()
    decay = (T - player.last_spawnkill_time) / decay_time

    return player.spawnkill_score - floor(decay)



def check_spawnkill(victim, killer, kill_type, grenade):
    if killer is None: return
    T = monotonic()
    ds = killer.protocol.map_info.extensions

    config = ds.get("arena_spawnkill")
    if config is None: return

    # Spawnkill of inactive player does not ruin the game for other
    # players and should not result in punishment
    if T - victim.last_activity_time > afk_time_threshold:
        return

    # Grenade kills are not really contributing to spawncamping due to
    # limited grenade count. Furthermore, in some situation it can be
    # considered a valid tactic to extract intel from protected base.
    #
    # On the other hand, grenade teamkills can easily be abused because
    # killer will die with killed teammates and respawn with new ammo.
    if kill_type == GRENADE_KILL and killer.team is not victim.team:
        return

    spawnkill_period       = config.get("spawnkill_period",      1.8)
    score_cap              = config.get("score_cap",              10)
    punishment_threshold   = config.get("punishment_threshold",    5)
    nade_teamkill_period   = config.get("nade_teamkill_period",  4.0)
    punished_period_mult   = config.get("punished_period_mult",  1.5)

    score = get_decayed_score(killer)
    corrected_period = spawnkill_period

    # Spawnkilling teammates with grenade should respect fuse time
    if kill_type == GRENADE_KILL:
        corrected_period = nade_teamkill_period

    # If killer has gained enough score for punishment spawnkill period
    # should be less forgiving
    if score > punishment_threshold:
        corrected_period *= punished_period_mult

    if (T - victim.last_spawn_time) > corrected_period:
        return

    killer.spawnkill_score     = min(score_cap, score + 1)
    killer.last_spawnkill_time = T
    killer.spawnkill_time_deque.appendleft(T)

    if killer.spawnkill_score < punishment_threshold:
        return

    killer.on_spawnkill_warning(victim, kill_type, grenade)

    killer.on_spawnkill_punishment(victim, kill_type, grenade)



def handle_spawnkill_warning(victim, killer, kill_type, grenade):
    if killer.warned_of_spawnkill: return

    killer.warned_of_spawnkill = True
    killer.send_chat_error("Spawnkilling will be punished")



def handle_spawnkill_punishment(victim, killer, kill_type, grenade):
    ds = killer.protocol.map_info.extensions

    config = ds.get("arena_spawnkill")
    if config is None: return

    punishment_threshold   = config.get("punishment_threshold",    5)
    punishment_damage_mult = config.get("punishment_damage_mult", 10)

    # Every spawnkill above punishment threshold results in increasing damage
    punishment = (killer.spawnkill_score - punishment_threshold) * punishment_damage_mult

    if punishment == 0: return

    # Notify other players, most importantly the victims so that they would
    # stay, knowing that spawnkilling will be prevented
    if killer.hp > punishment:
        message = f"{killer.name} was punished for spawnkilling (-{punishment} hp)"
    else:
        killer.send_chat_error("You pay the price")
        message = f"{killer.name} was punished for spawnkilling and died"

    killer.protocol.broadcast_chat(message)

    killer.hit(punishment)
