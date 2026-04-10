import random

def guess_the_number():
    print("Welcome to the Guess the Number game!")
    attempts = 0
    win_streak = 0

    while True:
        lower_limit = int(input("Enter the lower limit for the range: "))
        upper_limit = int(input("Enter the upper limit for the range: "))
        secret_number = random.randint(lower_limit, upper_limit)
        print(f"Guess a number between {lower_limit} and {upper_limit}.")

        remaining_attempts = 10  # Limited guesses
        attempts = 0

        while attempts < remaining_attempts:
            try:
                guess = int(input("Your guess: "))
                attempts += 1

                if guess < lower_limit or guess > upper_limit:
                    print(f"Please enter a number between {lower_limit} and {upper_limit}.")
                elif guess < secret_number:
                    print("Too low. Try again.")
                elif guess > secret_number:
                    print("Too high. Try again.")
                else:
                    print(f"Congratulations! You guessed the number {secret_number} in {attempts} attempts.")
                    win_streak += 1
                    print(f"Your win streak is {win_streak}.")
                    break
            except ValueError:
                print("Invalid input. Please enter a valid number.")

        print(f"Out of attempts. The secret number was {secret_number}.")
        play_again = input("Do you want to play again? (yes/no): ").lower()
        if play_again != "yes":
            print(f"Your final win streak is {win_streak}. Thanks for playing!")
            break

if __name__ == "__main__":
    guess_the_number()
    print("""
Enhancement Tasks for Guess the Number Game (Easy Level):
1. Limited Guesses: Limit the number of guesses a player can make (e.g., 10 guesses).
2. Feedback: Provide feedback to the player about how many guesses they have left.
3. Randomize Secret Number: Instead of a fixed range, randomly choose the lower and upper limits for each game.
4. Error Handling: Improve error handling by catching exceptions for non-integer inputs and asking the player to try again with a valid number.
5. Play Again: After the game ends (win or lose), ask the player if they want to play again. If they say yes, start a new game with a new random number.
6. Display Range: When the game starts, display the range of numbers (e.g., 'Guess a number between 1 and 100').
7. Hint Button: Add a 'Hint' button that the player can click to receive a hint about the secret number. The hint could be something simple like 'The number is even' or 'The number is a multiple of 5.'
8. Win Streak: Keep track of the player's win streak (consecutive wins) and display it after each game.
9. Beginner Tips: Provide beginner tips or rules at the beginning of the game to help new players understand how to play.
10. Customizable Range: Allow the player to choose the range of numbers they want to guess within (e.g., between 1 and 50 or 1 and 20) at the start of each game.
""")

