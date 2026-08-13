"""Role assignment and role changes. Placeholder for the next phase.

Will manage roles (e.g. leader, scout, relay) and let agents change roles during
a mission in response to failures or new information.
"""


class RoleManager:
    def assign(self, agents):
        raise NotImplementedError("roles are part of the next phase")
