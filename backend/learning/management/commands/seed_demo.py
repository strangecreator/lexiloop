from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from learning.models import Flashcard, Pool, UserProfile

CARDS = [
    ('meticulous', 'adjective', 'məˈtɪkjələs', 'Very careful and precise.', 'Showing great attention to every detail.', ['careful', 'thorough']),
    ('to take something for granted', 'phrase', '', 'To assume something will always be available.', 'To fail to appreciate something because you assume it is permanent or guaranteed.', ['assume']),
    ('ubiquitous', 'adjective', 'juːˈbɪkwɪtəs', 'Present or found everywhere.', 'Seeming to be present everywhere at the same time.', ['widespread', 'omnipresent']),
    ('a double-edged sword', 'idiom', '', 'Something with both benefits and drawbacks.', 'A situation or thing that has both helpful and harmful consequences.', []),
]

class Command(BaseCommand):
    help = 'Create a demo account and starter vocabulary pool.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='demo')
        parser.add_argument('--password', default='demo-pass-123')

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(username=options['username'])
        user.set_password(options['password'])
        user.save()
        UserProfile.objects.get_or_create(user=user)
        pool, _ = Pool.objects.get_or_create(user=user, name='Advanced English', defaults={'description': 'A polished starter set.'})
        for term, pos, ipa, short, definition, synonyms in CARDS:
            Flashcard.objects.get_or_create(
                pool=pool, normalized_term=term.casefold(),
                defaults={'term': term, 'part_of_speech': pos, 'ipa': ipa, 'short_definition': short,
                          'definition': definition, 'synonyms': synonyms,
                          'examples': [{'sentence': f'Here is a natural example using “{term}”.', 'note': ''}]},
            )
        self.stdout.write(self.style.SUCCESS(f"Demo ready: {user.username} / {options['password']}"))
