def fibonacci(count):
    """첫 항이 1인 피보나치 수열의 처음 count개 항을 반환합니다."""
    if count <= 0:
        return []

    sequence = [1, 1]
    while len(sequence) < count:
        sequence.append(sequence[-1] + sequence[-2])

    return sequence[:count]


try:
    count = int(input("출력할 항의 개수를 입력하세요: "))
    if count <= 0:
        print("항의 개수는 1 이상이어야 합니다.")
    else:
        print(*fibonacci(count))
except ValueError:
    print("항의 개수는 정수로 입력해 주세요.")
