from common import axl


def main():
    # parse args
    # setup logging
    # setup server_state
    # setup axl recv

    # on recv matchmaking request:
    #   add to matchmaking queue
    #   if there are enough players in the matchmaking queue:
    #       create a new game instance
    #       remove players from matchmaking queue
    #       add players to game instance

    print(axl.get_self_public_key())




if __name__ == "__main__":
    main()