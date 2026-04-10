import random

def choose_random_word():
    words = ["python", "hangman", "programming", "challenge", "computer"]
    return random.choice(words)

def display_word(word, guessed_letters):
    displayed_word = ""
    for letter in word:
        if letter in guessed_letters:
            displayed_word += letter
        else:
            displayed_word += "_"
    return displayed_word

def hangman():
    print("Welcome to Hangman!")
    secret_word = choose_random_word()
    guessed_letters = []
    attempts = 6  # Number of allowed incorrect guesses

    while attempts > 0:
        print("\nWord:", display_word(secret_word, guessed_letters))
        guess = input("Guess a letter: ").lower()

        if len(guess) != 1 or not guess.isalpha():
            print("Invalid input. Please enter a single letter.")
            continue

        if guess in guessed_letters:
            print("You already guessed that letter.")
            continue

        guessed_letters.append(guess)

        if guess in secret_word:
            print("Correct guess!")
        else:
            attempts -= 1
            print(f"Incorrect guess. You have {attempts} attempts left.")

        if set(secret_word) == set(guessed_letters):
            print("\nCongratulations! You've guessed the word:", secret_word)
            break

    if attempts == 0:
        print("\nGame over! The word was:", secret_word)

if __name__ == "__main__":
    hangman()
    print("""
Coding Challenge for Hangman Game :
1. Add more words to the word list used for the game.
2. Increase the number of incorrect guesses allowed.
3. Implement a scoring system where the player earns points for correct guesses and loses points for incorrect guesses.
4. Create a function to validate user input for letters only and ask for a new guess if the input is invalid.
5. Allow the player to play again after the game ends.
""")
