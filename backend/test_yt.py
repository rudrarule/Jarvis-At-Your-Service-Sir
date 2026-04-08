from tools.music_tool import play_music

def test_search():
    try:
        result = play_music("starlight by muse")
        print(result)
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    test_search()
