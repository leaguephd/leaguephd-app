# TODO: confirm it is okay with tournament draft
class ChampSelect:
    def __init__(self):
        self.active = False
        self.draft_type = None

        self.my_side = None

        self.num_banned = 0
        self.bans = [None] * 10

        self.num_picked = 0
        self.picks = [
            [
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
            ],
            [
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
            ],
        ]

        self.has_pick_started = False

    def __repr__(self):
        return {
            'active': self.active,
            'draft_type': self.draft_type,
            'my_side': self.my_side,
            'num_banned': self.num_banned,
            'num_picked': self.num_picked,
            'bans': self.bans,
            'picks': self.picks,
            'has_pick_started': self.has_pick_started,
        }

    def __str__(self):
        return str(self.__repr__())

    def reset(self):
        self.active = False
        self.draft_type = None

        self.my_side = None

        self.num_banned = 0
        self.bans = [None] * 10

        self.num_picked = 0
        self.picks = [
            [
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
            ],
            [
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
                {'champion_id': None, 'role': None},
            ],
        ]

        self.has_pick_started = False

    def update(self, session):
        def map_assignedPosition_to_role(position):
            dict_position = {
                'top': 'TOP',
                'jungle': 'JGL',
                'middle': 'MID',
                'bottom': 'ADC',
                'utility': 'SUP',
            }

            try:
                return dict_position[position]
            except KeyError:
                return None

        def get_action_bans(actions):
            action_bans = []
            for action in actions:
                for subaction in action:
                    if subaction['type'] == 'ban':
                        action_bans.append(subaction)
            return action_bans

        def get_action_picks(actions):
            action_picks = []
            for action in actions:
                for subaction in action:
                    if subaction['type'] == 'pick':
                        action_picks.append(subaction)
            return action_picks

        updated = False
        dict_updated = {
            'mode': None,
            'insert_list': [],
            'to_pick_phase': False,
        }

        if not self.active:
            if not session['hasSimultaneousPicks']:
                self.active = True

            if len(session['actions'][0]) == 10:
                # solo ranked/flex: start with 10 bans
                self.draft_type = 'solo'
            else:
                self.draft_type = 'tournament'

        if self.active:
            # set my_side
            if self.my_side is None:
                if session['localPlayerCellId'] <= 4:
                    self.my_side = 0
                else:
                    self.my_side = 1
                updated = True

            # bans
            this_num_banned = 0
            this_bans = self.bans
            i_ban_blue = 0
            i_ban_red = 0
            action_bans = get_action_bans(session['actions'])
            for action in action_bans:
                action_side = 0 if action['actorCellId'] <= 4 else 1
                if action['completed']:
                    ban_slot = i_ban_blue if action_side == 0 else 5 + i_ban_red
                    this_bans[ban_slot] = action['championId']
                    this_num_banned += 1

                if action_side == 0:
                    i_ban_blue += 1
                else:
                    i_ban_red += 1

            if this_num_banned > self.num_banned:
                self.bans = this_bans
                self.num_banned = this_num_banned
                updated = True
                dict_updated['mode'] = 'ban'

            # picks
            this_num_picked = 0
            action_picks = get_action_picks(session['actions'])

            # check if pick phase has started
            if not self.has_pick_started:
                for action in action_picks:
                    if action['completed'] or action['isInProgress']:
                        self.has_pick_started = True
                        dict_updated['to_pick_phase'] = True
                        updated = True
                        break

            if self.has_pick_started:
                for action in action_picks:
                    if action['completed']:
                        this_num_picked += 1

                        picks_team = 0 if action['actorCellId'] <= 4 else 1
                        picks_slot = action['actorCellId'] if action['actorCellId'] <= 4 else action['actorCellId'] - 5
                        if self.picks[picks_team][picks_slot]['champion_id'] is None:
                            self.picks[picks_team][picks_slot]['champion_id'] = action['championId']

                            # update role if ally
                            if action['isAllyAction']:
                                if self.my_side == 0:
                                    this_pick_myteam = session['myTeam'][action['actorCellId']]
                                else:
                                    this_pick_myteam = session['myTeam'][action['actorCellId'] - 5]
                                self.picks[picks_team][picks_slot]['role'] = map_assignedPosition_to_role(
                                    this_pick_myteam['assignedPosition'])

                            # update dict_updated
                            dict_updated['insert_list'].append({
                                'side': picks_team,
                                'slot': picks_slot,
                                'champion_id': self.picks[picks_team][picks_slot]['champion_id'],
                                'role': self.picks[picks_team][picks_slot]['role']
                            })

                if this_num_picked > self.num_picked:
                    updated = True
                    self.num_picked = this_num_picked

                if self.num_picked > 9:
                    self.active = False

        return updated, dict_updated
