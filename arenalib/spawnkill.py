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


PUNISHMENT_SCORE_THRESHOLD = 5
PUNISHMENT_DMG_MULTIPLIER  = 10
SCORE_CAP                  = 10

DEFAULT_PERIOD         = 1.8
DEFAULT_CHECK_INTERVAL = 30
DEFAULT_DECAY_TIME     = 30

WARNING_POPUP        = "Spawnkilling will be punished"
DEARH_POPUP          = "You pay the price"
BROADCAST_HIT_TEXT   = "{} was punished for spawnkilling (-{} hp)"
BROADCAST_DEATH_TEXT = "{} was punished for spawnkilling and died"

arena_section = config.section("arena")

# Some maps might encourage fast-pased gameplay where kill right after spawn
# wont be considered spawncamping (for example: close quarters ffa maps)
period             = arena_section.option("spawnkill_period", DEFAULT_PERIOD).get()
check_interval     = arena_section.option("spawnkill_check_interval", DEFAULT_CHECK_INTERVAL).get()
decay_time         = arena_section.option("spawnkill_decay_time", DEFAULT_DECAY_TIME).get()
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

    score = get_decayed_score(killer)
    corrected_period = period

    # Spawnkilling teammates with grenade should respect fuse time
    if kill_type == GRENADE_KILL: corrected_period = 4.0

    # If killer has gained the enough score for punishment spawnkill period
    # should be less forgiving
    if score > PUNISHMENT_SCORE_THRESHOLD: corrected_period *= 1.5

    if (T - victim.last_spawn_time) > corrected_period:
        return

    killer.spawnkill_score     = min(SCORE_CAP, score + 1)
    killer.last_spawnkill_time = T
    killer.spawnkill_time_deque.appendleft(T)

    if killer.spawnkill_score < PUNISHMENT_SCORE_THRESHOLD:
        return

    if not killer.warned_of_spawnkill:
        killer.warned_of_spawnkill = True
        killer.send_chat_error(WARNING_POPUP)

    # Every spawnkill above punishment threshold results in increasing damage
    punishment = (killer.spawnkill_score - PUNISHMENT_SCORE_THRESHOLD)
    punishment *= PUNISHMENT_DMG_MULTIPLIER

    if punishment == 0: return

    # Notify other players, most importantly the victims so that they would
    # stay, knowing that spawnkilling will be prevented
    if killer.hp > punishment:
        message = BROADCAST_HIT_TEXT.format(killer.name, punishment)
    else:
        killer.send_chat_error(DEARH_POPUP)
        message = BROADCAST_DEATH_TEXT.format(killer.name)

    killer.protocol.broadcast_chat(message)

    killer.hit(punishment)
