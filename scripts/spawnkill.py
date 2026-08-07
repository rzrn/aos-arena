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

from collections import deque
from time import monotonic
from math import floor

from horseradish.commands import player_only, command, get_player
from horseradish.utils import timeparse
from horseradish.config import config

from pyspades.constants import GRENADE_KILL
from pyspades.common import prettify_timespan

from arenalib.common import afk_time_threshold


@command('spawnkillcount', 'skc')
def c_spawnkillcount(connection, nickname = None, timeval = None):
    """
    Report a number of spawnkills for a given period of time
    /spawnkillcount or /skc [player] [timedelta]
    """

    protocol = connection.protocol

    player = connection if nickname is None else get_player(protocol, nickname)

    Δt = 3600 if timeval is None else timeparse(timeval)
    if Δt is None: return "'{}' was not recognized as a valid time value".format(timeval)

    count = get_spawnkill_count(player, Δt)
    M = connection.spawnkill_time_deque.maxlen

    score = get_decayed_score(player)

    if count > M:
        return "{}: more than {} spawnkill(s) in {}, with the score of {}".format(
            player.name, count, prettify_timespan(Δt), score
        )
    else:
        return "{}: {} spawnkill(s) in {}, with the score of {}".format(
            player.name, count, prettify_timespan(Δt), score
        )



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

    decay_time = ds.get("arena_spawnkill_decay_time", 0)
    if decay_time == 0: return 0

    if not isinstance(player, protocol.connection_class):
        return 0

    if player.last_spawnkill_time == 0:
        return player.spawnkill_score

    T = monotonic()
    decay = (T - player.last_spawnkill_time) / decay_time

    return max(player.spawnkill_score - floor(decay), 0)



def check_spawnkill(victim, killer, kill_type, grenade):
    if killer is None: return
    T = monotonic()
    ds = killer.protocol.map_info.extensions

    if T0 := victim.last_activity_time:
        # Spawnkill of inactive player does not ruin the game for other
        # players and should not result in punishment
        if T - T0 > afk_time_threshold:
            return
    else:
        return # No activity has been observed yet

    # Grenade kills are not really contributing to spawncamping due to
    # limited grenade count. Furthermore, in some situation it can be
    # considered a valid tactic to extract intel from protected base.
    #
    # On the other hand, grenade teamkills can easily be abused because
    # killer will die with killed teammates and respawn with new ammo.
    if kill_type == GRENADE_KILL and killer.team is not victim.team:
        return

    spawnkill_period     = ds.get("arena_spawnkill_period",               0)
    score_cap            = ds.get("arena_spawnkill_score_cap",            0)
    punishment_threshold = ds.get("arena_spawnkill_punishment_threshold", 0)
    nade_teamkill_period = ds.get("arena_spawnkill_nade_teamkill_period", 0)
    punished_period_mult = ds.get("arena_spawnkill_punished_period_mult", 0)

    score = get_decayed_score(killer)
    corrected_period = spawnkill_period

    # Spawnkilling teammates with grenade should respect fuse time
    if kill_type == GRENADE_KILL:
        corrected_period = nade_teamkill_period

    # If killer has gained enough score for punishment spawnkill period
    # should be less forgiving
    if score > punishment_threshold:
        corrected_period *= punished_period_mult

    if T - victim.last_spawn_time > corrected_period:
        return

    killer.spawnkill_score     = min(score_cap, score + 1)
    killer.last_spawnkill_time = T
    killer.spawnkill_time_deque.appendleft(T)

    killer.on_spawnkill(victim, kill_type, grenade)



def handle_spawnkill(victim, killer, kill_type, grenade):
    ds = killer.protocol.map_info.extensions

    punishment_threshold   = ds.get("arena_spawnkill_punishment_threshold",   0)
    punishment_damage_mult = ds.get("arena_spawnkill_punishment_damage_mult", 0)

    if killer.spawnkill_score < punishment_threshold:
        return

    if not killer.warned_of_spawnkill:
        killer.warned_of_spawnkill = True
        killer.send_chat_error("Spawnkilling will be punished")

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



def apply_script(protocol, connection, config):
    class SpawnkillConnection(connection):
        def __init__(self, *w, **kw):
            connection.__init__(self, *w, **kw)

            self.spawnkill_time_deque = deque(maxlen = 30)
            self.last_spawn_time      = 0
            self.last_spawnkill_time  = 0
            self.spawnkill_score      = 0
            self.warned_of_spawnkill  = False



        def on_kill(self, killer, kill_type, grenade):
            retval = connection.on_kill(self, killer, kill_type, grenade)

            if retval is False: return False

            check_spawnkill(self, killer, kill_type, grenade)

            return retval



        def on_spawn(self, loc):
            self.last_spawn_time = monotonic()

            return connection.on_spawn(self, loc)



        def on_spawnkill(self, victim, kill_type, grenade):
            handle_spawnkill(victim, self, kill_type, grenade)



    class SpawnkillProtocol(protocol):
        def on_map_change(self, M):
            for player in self.connections.values():
                player.warned_of_spawnkill = False

            return protocol.on_map_change(self, M)



    return SpawnkillProtocol, SpawnkillConnection
