def print_board(board):
    for row in board:
        print(" | ".join(row))
        print("-" * 9)

def check_win(board, player):
    for row in board:
        if all(cell == player for cell in row):
            return True
    for col in range(3):
        if all(board[row][col] == player for row in range(3)):
            return True
    if all(board[i][i] == player for i in range(3)) or all(board[i][2 - i] == player for i in range(3)):
        return True
    return False

def is_full(board):
    return all(cell != " " for row in board for cell in row)

def play_tic_tac_toe():
    print("Welcome to Tic-Tac-Toe!")
    board = [[" " for _ in range(3)] for _ in range(3)]
    player = "X"
    game_over = False

    while not game_over:
        print_board(board)
        row = int(input(f"Player {player}, enter row (0, 1, 2): "))
        col = int(input(f"Player {player}, enter column (0, 1, 2): "))

        if board[row][col] == " ":
            board[row][col] = player
            if check_win(board, player):
                print_board(board)
                print(f"Player {player} wins! Congratulations!")
                game_over = True
            elif is_full(board):
                print_board(board)
                print("It's a draw! The game is over.")
                game_over = True
            else:
                player = "O" if player == "X" else "X"
        else:
            print("Invalid move. That cell is already occupied. Try again.")

if __name__ == "__main__":
    play_tic_tac_toe()

    print("""
Coding Challenge for Tic-Tac-Toe Game (Easy Level):
1. Add a replay option to play multiple games in a row.
2. Implement a simple AI opponent for single-player mode.
3. Create a scoring system to keep track of wins, losses, and draws.
4. Improve the user interface with clear instructions and formatting.
5. Allow customizable player names.
6. Increase the board size for a larger and more challenging game (e.g., 4x4 or 5x5).
7. Add sound effects or animations for a more engaging experience.
8. Implement a feature to exit the game at any time.
""")
